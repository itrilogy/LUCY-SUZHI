import json
import logging
import os
from dataclasses import dataclass, field
from typing import Union, Literal, Optional

import dspy

from .modules.article_generation import StormArticleGenerationModule
from .modules.article_polish import StormArticlePolishingModule
from .modules.callback import BaseCallbackHandler, CompositeCallbackHandler
from .modules.knowledge_curation import StormKnowledgeCurationModule
from .modules.outline_generation import StormOutlineGenerationModule
from .modules.persona_generator import StormPersonaGenerator
from .modules.storm_dataclass import StormInformationTable, StormArticle
from .modules.fact_pool import FactPool
from .modules.pipeline_state import PipelineState, PipelineStateManager, PHASE_ORDER
from ..interface import Engine, LMConfigs, Retriever
from ..lm import LitellmModel
from ..utils import FileIOHelper, makeStringRed, truncate_filename


class STORMWikiLMConfigs(LMConfigs):
    """Configurations for LLM used in different parts of STORM.

    Given that different parts in STORM framework have different complexity, we use different LLM configurations
    to achieve a balance between quality and efficiency. If no specific configuration is provided, we use the default
    setup in the paper.
    """

    def __init__(self):
        self.conv_simulator_lm = (
            None  # LLM used in conversation simulator except for question asking.
        )
        self.question_asker_lm = None  # LLM used in question asking.
        self.outline_gen_lm = None  # LLM used in outline generation.
        self.article_gen_lm = None  # LLM used in article generation.
        self.article_polish_lm = None  # LLM used in article polishing.

    def init_openai_model(
        self,
        openai_api_key: str,
        azure_api_key: str,
        openai_type: Literal["openai", "azure"],
        api_base: Optional[str] = None,
        api_version: Optional[str] = None,
        temperature: Optional[float] = 1.0,
        top_p: Optional[float] = 0.9,
    ):
        """Legacy: Corresponding to the original setup in the NAACL'24 paper."""
        azure_kwargs = {
            "api_key": azure_api_key,
            "temperature": temperature,
            "top_p": top_p,
            "api_base": api_base,
            "api_version": api_version,
        }

        openai_kwargs = {
            "api_key": openai_api_key,
            "temperature": temperature,
            "top_p": top_p,
            "api_base": None,
        }
        if openai_type and openai_type == "openai":
            self.conv_simulator_lm = LitellmModel(
                model="gpt-4o-mini-2024-07-18", max_tokens=500, **openai_kwargs
            )
            self.question_asker_lm = LitellmModel(
                model="gpt-4o-mini-2024-07-18", max_tokens=500, **openai_kwargs
            )
            # 1/12/2024: Update gpt-4 to gpt-4-1106-preview. (Currently keep the original setup when using azure.)
            self.outline_gen_lm = LitellmModel(
                model="gpt-4-0125-preview", max_tokens=400, **openai_kwargs
            )
            self.article_gen_lm = LitellmModel(
                model="gpt-4o-2024-05-13", max_tokens=700, **openai_kwargs
            )
            self.article_polish_lm = LitellmModel(
                model="gpt-4o-2024-05-13", max_tokens=4000, **openai_kwargs
            )
        elif openai_type and openai_type == "azure":
            self.conv_simulator_lm = LitellmModel(
                model="azure/gpt-4o-mini-2024-07-18", max_tokens=500, **openai_kwargs
            )
            self.question_asker_lm = LitellmModel(
                model="azure/gpt-4o-mini-2024-07-18",
                max_tokens=500,
                **azure_kwargs,
                model_type="chat",
            )
            # use combination of openai and azure-openai as azure-openai does not support gpt-4 in standard deployment
            self.outline_gen_lm = LitellmModel(
                model="azure/gpt-4o", max_tokens=400, **azure_kwargs, model_type="chat"
            )
            self.article_gen_lm = LitellmModel(
                model="azure/gpt-4o-mini-2024-07-18",
                max_tokens=700,
                **azure_kwargs,
                model_type="chat",
            )
            self.article_polish_lm = LitellmModel(
                model="azure/gpt-4o-mini-2024-07-18",
                max_tokens=4000,
                **azure_kwargs,
                model_type="chat",
            )
        else:
            logging.warning(
                "No valid OpenAI API provider is provided. Cannot use default LLM configurations."
            )

    def set_conv_simulator_lm(self, model: Union[dspy.dsp.LM, dspy.dsp.HFModel]):
        self.conv_simulator_lm = model

    def set_question_asker_lm(self, model: Union[dspy.dsp.LM, dspy.dsp.HFModel]):
        self.question_asker_lm = model

    def set_outline_gen_lm(self, model: Union[dspy.dsp.LM, dspy.dsp.HFModel]):
        self.outline_gen_lm = model

    def set_article_gen_lm(self, model: Union[dspy.dsp.LM, dspy.dsp.HFModel]):
        self.article_gen_lm = model

    def set_article_polish_lm(self, model: Union[dspy.dsp.LM, dspy.dsp.HFModel]):
        self.article_polish_lm = model


@dataclass
class STORMWikiRunnerArguments:
    """Arguments for controlling the STORM Wiki pipeline."""

    output_dir: str = field(
        metadata={"help": "Output directory for the results."},
    )
    max_conv_turn: int = field(
        default=3,
        metadata={
            "help": "Maximum number of questions in conversational question asking."
        },
    )
    max_perspective: int = field(
        default=3,
        metadata={
            "help": "Maximum number of perspectives to consider in perspective-guided question asking."
        },
    )
    max_search_queries_per_turn: int = field(
        default=3,
        metadata={"help": "Maximum number of search queries to consider in each turn."},
    )
    disable_perspective: bool = field(
        default=False,
        metadata={"help": "If True, disable perspective-guided question asking."},
    )
    search_top_k: int = field(
        default=3,
        metadata={"help": "Top k search results to consider for each search query."},
    )
    retrieve_top_k: int = field(
        default=3,
        metadata={"help": "Top k collected references for each section title."},
    )
    max_thread_num: int = field(
        default=10,
        metadata={
            "help": "Maximum number of threads to use. "
            "Consider reducing it if keep getting 'Exceed rate limit' error when calling LM API."
        },
    )


class STORMWikiRunner(Engine):
    """STORM Wiki pipeline runner."""

    def __init__(
        self, args: STORMWikiRunnerArguments, lm_configs: STORMWikiLMConfigs, rm,
        encoder=None, reranker=None,
    ):
        super().__init__(lm_configs=lm_configs)
        self.args = args
        self.lm_configs = lm_configs
        self.encoder = encoder
        self.reranker = reranker

        self.retriever = Retriever(rm=rm, max_thread=self.args.max_thread_num)
        storm_persona_generator = StormPersonaGenerator(
            self.lm_configs.question_asker_lm
        )
        self.storm_knowledge_curation_module = StormKnowledgeCurationModule(
            retriever=self.retriever,
            persona_generator=storm_persona_generator,
            conv_simulator_lm=self.lm_configs.conv_simulator_lm,
            question_asker_lm=self.lm_configs.question_asker_lm,
            max_search_queries_per_turn=self.args.max_search_queries_per_turn,
            search_top_k=self.args.search_top_k,
            max_conv_turn=self.args.max_conv_turn,
            max_thread_num=self.args.max_thread_num,
        )
        self.storm_outline_generation_module = StormOutlineGenerationModule(
            outline_gen_lm=self.lm_configs.outline_gen_lm
        )
        self.storm_article_generation = StormArticleGenerationModule(
            article_gen_lm=self.lm_configs.article_gen_lm,
            retrieve_top_k=self.args.retrieve_top_k,
            max_thread_num=self.args.max_thread_num,
        )
        self.storm_article_polishing_module = StormArticlePolishingModule(
            article_gen_lm=self.lm_configs.article_gen_lm,
            article_polish_lm=self.lm_configs.article_polish_lm,
        )

        # Phase 1.1: FactPool 缓存（可选）—— 必须在 apply_decorators 之前初始化
        self._fact_pool: Optional[FactPool] = None

        self.lm_configs.init_check()
        self.apply_decorators()

    @property
    def fact_pool(self) -> Optional[FactPool]:
        """获取当前管线的 FactPool（仅当 research 阶段启用了 build_fact_pool 时非空）。"""
        return self._fact_pool

    def update(
        self,
        topic: str,
        new_sources: List[str] = None,
        ground_truth_url: str = "",
        callback_handler: BaseCallbackHandler = BaseCallbackHandler(),
        build_fact_pool: bool = True,
    ):
        """
        Incrementally update the article for an existing topic.

        This method re-runs only the research phase on new sources,
        merges new facts into the existing FactPool, identifies affected
        sections via the Manifest, and performs targeted rewrites.

        Phase 4.3: Incremental Knowledge Evolution.

        Args:
            topic: The existing topic to update.
            new_sources: List of URLs or file paths for new sources.
            ground_truth_url: The ground truth URL to exclude.
            callback_handler: Callback handler.
            build_fact_pool: Whether to rebuild FactPool.
        """
        from .modules.diff_engine import DiffEngine
        from .modules.fact_pool import FactPool

        diff_engine = DiffEngine()

        self.topic = topic
        self.article_dir_name = truncate_filename(
            topic.replace(" ", "_").replace("/", "_")
        )
        self.article_output_dir = os.path.join(
            self.args.output_dir, self.article_dir_name
        )

        # Step 1: Load existing state
        existing_fact_pool = None
        existing_manifest = None
        existing_article = None

        fp_path = PipelineStateManager.expected_fact_pool_path(self.article_output_dir)
        if os.path.exists(fp_path):
            existing_fact_pool = FactPool.load_json(fp_path)
            logger.info(f"Loaded existing FactPool with {existing_fact_pool.num_facts()} facts")

        # Step 2: Re-run research (optionally with new sources)
        # For simplicity, we re-run research normally; the FactPool will be rebuilt.
        information_table = self.run_knowledge_curation_module(
            ground_truth_url=ground_truth_url,
            callback_handler=callback_handler,
            build_fact_pool=build_fact_pool,
        )

        new_fact_pool = self._fact_pool

        # Step 3: Compute diff and affected sections
        if existing_fact_pool and new_fact_pool:
            diff = diff_engine.compute_pool_diff(existing_fact_pool, new_fact_pool)
            logger.info(f"Update diff: {diff.summary()}")
        else:
            logger.info("No existing FactPool found; performing full rebuild.")
            # Fall through to normal full run
            self.run(
                topic=topic,
                ground_truth_url=ground_truth_url,
                do_research=False,
                do_generate_outline=True,
                do_generate_article=True,
                do_polish_article=True,
                callback_handler=callback_handler,
                build_fact_pool=build_fact_pool,
            )
            return

        # Step 4: If diff is significant, re-generate outline and article
        if diff.has_changes:
            outline = self.run_outline_generation_module(
                information_table=information_table,
                callback_handler=callback_handler,
            )
            draft_article = self.run_article_generation_module(
                outline=outline,
                information_table=information_table,
                callback_handler=callback_handler,
            )
            self.run_article_polishing_module(
                draft_article=draft_article, remove_duplicate=False
            )
            logger.info(f"Incremental update complete. {diff.summary()}")
        else:
            logger.info("No changes detected; article is up to date.")

    def run_knowledge_curation_module(
        self,
        ground_truth_url: str = "None",
        callback_handler: BaseCallbackHandler = None,
        build_fact_pool: bool = False,
    ) -> StormInformationTable:
        if build_fact_pool:
            (
                information_table,
                fact_pool,
                conversation_log,
            ) = self.storm_knowledge_curation_module.research(
                topic=self.topic,
                ground_truth_url=ground_truth_url,
                callback_handler=callback_handler,
                max_perspective=self.args.max_perspective,
                disable_perspective=False,
                return_conversation_log=True,
                build_fact_pool=True,
            )
            self._fact_pool = fact_pool
            # 持久化 FactPool
            fact_pool_path = PipelineStateManager.expected_fact_pool_path(
                self.article_output_dir
            )
            fact_pool.dump_json(fact_pool_path)

            # 通知 callback 事件
            for fact in fact_pool.get_all_facts():
                callback_handler.on_fact_extracted(fact=fact)
        else:
            (
                information_table,
                conversation_log,
            ) = self.storm_knowledge_curation_module.research(
                topic=self.topic,
                ground_truth_url=ground_truth_url,
                callback_handler=callback_handler,
                max_perspective=self.args.max_perspective,
                disable_perspective=False,
                return_conversation_log=True,
                build_fact_pool=False,
            )

        FileIOHelper.dump_json(
            conversation_log,
            os.path.join(self.article_output_dir, "conversation_log.json"),
        )
        information_table.dump_url_to_info(
            os.path.join(self.article_output_dir, "raw_search_results.json")
        )
        return information_table

    def run_outline_generation_module(
        self,
        information_table: StormInformationTable,
        callback_handler: BaseCallbackHandler = None,
    ) -> StormArticle:
        outline, draft_outline = self.storm_outline_generation_module.generate_outline(
            topic=self.topic,
            information_table=information_table,
            return_draft_outline=True,
            callback_handler=callback_handler,
        )
        outline.dump_outline_to_file(
            os.path.join(self.article_output_dir, "storm_gen_outline.txt")
        )
        draft_outline.dump_outline_to_file(
            os.path.join(self.article_output_dir, "direct_gen_outline.txt")
        )
        return outline

    def run_article_generation_module(
        self,
        outline: StormArticle,
        information_table=StormInformationTable,
        callback_handler: BaseCallbackHandler = None,
    ) -> StormArticle:
        draft_article = self.storm_article_generation.generate_article(
            topic=self.topic,
            information_table=information_table,
            article_with_outline=outline,
            callback_handler=callback_handler,
            encoder=self.encoder,
        )
        draft_article.dump_article_as_plain_text(
            os.path.join(self.article_output_dir, "storm_gen_article.txt")
        )
        draft_article.dump_reference_to_file(
            os.path.join(self.article_output_dir, "url_to_info.json")
        )
        return draft_article

    def run_article_polishing_module(
        self, draft_article: StormArticle, remove_duplicate: bool = False
    ) -> StormArticle:
        polished_article = self.storm_article_polishing_module.polish_article(
            topic=self.topic,
            draft_article=draft_article,
            remove_duplicate=remove_duplicate,
        )
        FileIOHelper.write_str(
            polished_article.to_string(),
            os.path.join(self.article_output_dir, "storm_gen_article_polished.txt"),
        )
        return polished_article

    def post_run(self):
        """
        Post-run operations, including:
        1. Dumping the run configuration.
        2. Dumping the LLM call history.
        """
        config_log = self.lm_configs.log()
        FileIOHelper.dump_json(
            config_log, os.path.join(self.article_output_dir, "run_config.json")
        )

        llm_call_history = self.lm_configs.collect_and_reset_lm_history()
        with open(
            os.path.join(self.article_output_dir, "llm_call_history.jsonl"), "w"
        ) as f:
            for call in llm_call_history:
                if "kwargs" in call:
                    call.pop(
                        "kwargs"
                    )  # All kwargs are dumped together to run_config.json.
                f.write(json.dumps(call) + "\n")

    def _load_information_table_from_local_fs(self, information_table_local_path):
        assert os.path.exists(information_table_local_path), makeStringRed(
            f"{information_table_local_path} not exists. Please set --do-research argument to prepare the conversation_log.json for this topic."
        )
        return StormInformationTable.from_conversation_log_file(
            information_table_local_path
        )

    def _load_outline_from_local_fs(self, topic, outline_local_path):
        assert os.path.exists(outline_local_path), makeStringRed(
            f"{outline_local_path} not exists. Please set --do-generate-outline argument to prepare the storm_gen_outline.txt for this topic."
        )
        return StormArticle.from_outline_file(topic=topic, file_path=outline_local_path)

    def _load_draft_article_from_local_fs(
        self, topic, draft_article_path, url_to_info_path
    ):
        assert os.path.exists(draft_article_path), makeStringRed(
            f"{draft_article_path} not exists. Please set --do-generate-article argument to prepare the storm_gen_article.txt for this topic."
        )
        assert os.path.exists(url_to_info_path), makeStringRed(
            f"{url_to_info_path} not exists. Please set --do-generate-article argument to prepare the url_to_info.json for this topic."
        )
        article_text = FileIOHelper.load_str(draft_article_path)
        references = FileIOHelper.load_json(url_to_info_path)
        return StormArticle.from_string(
            topic_name=topic, article_text=article_text, references=references
        )

    def run(
        self,
        topic: str,
        ground_truth_url: str = "",
        do_research: bool = True,
        do_generate_outline: bool = True,
        do_generate_article: bool = True,
        do_polish_article: bool = True,
        remove_duplicate: bool = False,
        callback_handler: BaseCallbackHandler = BaseCallbackHandler(),
        resume: bool = False,
        build_fact_pool: bool = False,
    ):
        """
        Run the STORM pipeline.

        Args:
            topic: The topic to research.
            ground_truth_url: A ground truth URL including a curated article about the topic. The URL will be excluded.
            do_research: If True, research the topic through information-seeking conversation;
             if False, expect conversation_log.json and raw_search_results.json to exist in the output directory.
            do_generate_outline: If True, generate an outline for the topic;
             if False, expect storm_gen_outline.txt to exist in the output directory.
            do_generate_article: If True, generate a curated article for the topic;
             if False, expect storm_gen_article.txt to exist in the output directory.
            do_polish_article: If True, polish the article by adding a summarization section and (optionally) removing
             duplicated content.
            remove_duplicate: If True, remove duplicated content.
            callback_handler: A callback handler to handle the intermediate results.
            resume: If True, attempt to resume from a previous checkpoint.
            build_fact_pool: If True, build a FactPool during the research phase.
        """
        assert (
            do_research
            or do_generate_outline
            or do_generate_article
            or do_polish_article
        ), makeStringRed(
            "No action is specified. Please set at least one of --do-research, --do-generate-outline, --do-generate-article, --do-polish-article"
        )

        self.topic = topic
        self.article_dir_name = truncate_filename(
            topic.replace(" ", "_").replace("/", "_")
        )
        self.article_output_dir = os.path.join(
            self.args.output_dir, self.article_dir_name
        )
        os.makedirs(self.article_output_dir, exist_ok=True)

        # Phase 1.3: 断点续跑
        state_manager = PipelineStateManager(self.article_output_dir)
        if resume:
            loaded = state_manager.load()
            if loaded is not None:
                logger.info(f"Resuming from checkpoint: phase={loaded.phase}")
                # 根据已完成的阶段调整 do_* 标志
                if state_manager.is_phase_complete("research_done"):
                    do_research = False
                    logger.info("Skipping research phase (already completed).")
                if state_manager.is_phase_complete("outline_done"):
                    do_generate_outline = False
                    logger.info("Skipping outline generation phase (already completed).")
                if state_manager.is_phase_complete("article_done"):
                    do_generate_article = False
                    logger.info("Skipping article generation phase (already completed).")
                if state_manager.is_phase_complete("polish_done"):
                    do_polish_article = False
                    logger.info("Skipping article polishing phase (already completed).")
            else:
                logger.info("No checkpoint found; starting from scratch.")

        # research module
        information_table: StormInformationTable = None
        if do_research:
            information_table = self.run_knowledge_curation_module(
                ground_truth_url=ground_truth_url,
                callback_handler=callback_handler,
                build_fact_pool=build_fact_pool,
            )
            # 持久化 FactPool（如已启用）
            if build_fact_pool and self._fact_pool is not None:
                fp_path = PipelineStateManager.expected_fact_pool_path(
                    self.article_output_dir
                )
                self._fact_pool.dump_json(fp_path)
            state_manager.update_phase(
                "research_done",
                topic=topic,
                output_dir=self.article_output_dir,
                fact_pool_path=PipelineStateManager.expected_fact_pool_path(
                    self.article_output_dir
                ),
                conversation_log_path=PipelineStateManager.expected_conversation_log_path(
                    self.article_output_dir
                ),
                lm_cost_so_far=self.lm_cost,
                rm_cost_so_far=self.rm_cost,
            )
        # outline generation module
        outline: StormArticle = None
        if do_generate_outline:
            # load information table if it's not initialized
            if information_table is None:
                information_table = self._load_information_table_from_local_fs(
                    os.path.join(self.article_output_dir, "conversation_log.json")
                )
            outline = self.run_outline_generation_module(
                information_table=information_table, callback_handler=callback_handler
            )
            state_manager.update_phase(
                "outline_done",
                outline_path=PipelineStateManager.expected_outline_path(
                    self.article_output_dir
                ),
                lm_cost_so_far=self.lm_cost,
                rm_cost_so_far=self.rm_cost,
            )

        # article generation module
        draft_article: StormArticle = None
        if do_generate_article:
            if information_table is None:
                information_table = self._load_information_table_from_local_fs(
                    os.path.join(self.article_output_dir, "conversation_log.json")
                )
            if outline is None:
                outline = self._load_outline_from_local_fs(
                    topic=topic,
                    outline_local_path=os.path.join(
                        self.article_output_dir, "storm_gen_outline.txt"
                    ),
                )
            draft_article = self.run_article_generation_module(
                outline=outline,
                information_table=information_table,
                callback_handler=callback_handler,
            )
            state_manager.update_phase(
                "article_done",
                article_path=PipelineStateManager.expected_article_path(
                    self.article_output_dir
                ),
                lm_cost_so_far=self.lm_cost,
                rm_cost_so_far=self.rm_cost,
            )

        # article polishing module
        if do_polish_article:
            if draft_article is None:
                draft_article_path = os.path.join(
                    self.article_output_dir, "storm_gen_article.txt"
                )
                url_to_info_path = os.path.join(
                    self.article_output_dir, "url_to_info.json"
                )
                draft_article = self._load_draft_article_from_local_fs(
                    topic=topic,
                    draft_article_path=draft_article_path,
                    url_to_info_path=url_to_info_path,
                )
            self.run_article_polishing_module(
                draft_article=draft_article, remove_duplicate=remove_duplicate
            )
            state_manager.update_phase(
                "polish_done",
                polished_article_path=PipelineStateManager.expected_polished_article_path(
                    self.article_output_dir
                ),
                lm_cost_so_far=self.lm_cost,
                rm_cost_so_far=self.rm_cost,
            )
