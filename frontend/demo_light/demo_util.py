import base64
import datetime
import json
import os
import re
import sys
from typing import Optional

import markdown
import pytz
import streamlit as st

# If you install the source code instead of the `knowledge-storm` package,
# Uncomment the following lines:
import sys
sys.path.append('../../')
from knowledge_storm import (
    STORMWikiRunnerArguments,
    STORMWikiRunner,
    STORMWikiLMConfigs,
)
from knowledge_storm.storm_wiki.modules.callback import BaseCallbackHandler
from knowledge_storm.storm_wiki.modules.storm_dataclass import Persona
from knowledge_storm.utils import truncate_filename
from stoc import stoc

# 动态导入：根据 StormConfig 的活跃提供商选择 LM/RM 类
# 避免在启动时因缺少某个 provider 的依赖而崩溃
def _import_lm_class(class_name):
    """按需导入 LM 类。"""
    if class_name == "DeepSeekModel":
        from knowledge_storm.lm import DeepSeekModel as cls
    elif class_name == "OpenAIModel":
        from knowledge_storm.lm import OpenAIModel as cls
    elif class_name == "LitellmModel":
        from knowledge_storm.lm import LitellmModel as cls
    elif class_name == "ClaudeModel":
        from knowledge_storm.lm import ClaudeModel as cls
    elif class_name == "GoogleModel":
        from knowledge_storm.lm import GoogleModel as cls
    elif class_name == "OllamaClient":
        from knowledge_storm.lm import OllamaClient as cls
    else:
        from knowledge_storm.lm import LitellmModel as cls
    return cls


def _import_rm_class(class_name):
    """按需导入 RM 类。"""
    if class_name == "SearXNG":
        from knowledge_storm.rm import SearXNG as cls
    elif class_name == "DuckDuckGoSearchRM":
        from knowledge_storm.rm import DuckDuckGoSearchRM as cls
    elif class_name == "BingSearch":
        from knowledge_storm.rm import BingSearch as cls
    elif class_name == "SerperRM":
        from knowledge_storm.rm import SerperRM as cls
    elif class_name == "BraveRM":
        from knowledge_storm.rm import BraveRM as cls
    elif class_name == "YouRM":
        from knowledge_storm.rm import YouRM as cls
    else:
        from knowledge_storm.rm import DuckDuckGoSearchRM as cls
    return cls


class DemoFileIOHelper:
    @staticmethod
    def read_structure_to_dict(articles_root_path):
        """
        Reads the directory structure of articles stored in the given root path and
        returns a nested dictionary. The outer dictionary has article names as keys,
        and each value is another dictionary mapping file names to their absolute paths.

        Args:
            articles_root_path (str): The root directory path containing article subdirectories.

        Returns:
            dict: A dictionary where each key is an article name, and each value is a dictionary
                of file names and their absolute paths within that article's directory.
        """
        articles_dict = {}
        for topic_name in os.listdir(articles_root_path):
            topic_path = os.path.join(articles_root_path, topic_name)
            if os.path.isdir(topic_path):
                # Initialize or update the dictionary for the topic
                articles_dict[topic_name] = {}
                # Iterate over all files within a topic directory
                for file_name in os.listdir(topic_path):
                    file_path = os.path.join(topic_path, file_name)
                    articles_dict[topic_name][file_name] = os.path.abspath(file_path)
        return articles_dict

    @staticmethod
    def read_txt_file(file_path):
        """
        Reads the contents of a text file and returns it as a string.

        Args:
            file_path (str): The path to the text file to be read.

        Returns:
            str: The content of the file as a single string.
        """
        with open(file_path) as f:
            return f.read()

    @staticmethod
    def read_json_file(file_path):
        """
        Reads a JSON file and returns its content as a Python dictionary or list,
        depending on the JSON structure.

        Args:
            file_path (str): The path to the JSON file to be read.

        Returns:
            dict or list: The content of the JSON file. The type depends on the
                        structure of the JSON file (object or array at the root).
        """
        with open(file_path) as f:
            return json.load(f)

    @staticmethod
    def read_image_as_base64(image_path):
        """
        Reads an image file and returns its content encoded as a base64 string,
        suitable for embedding in HTML or transferring over networks where binary
        data cannot be easily sent.

        Args:
            image_path (str): The path to the image file to be encoded.

        Returns:
            str: The base64 encoded string of the image, prefixed with the necessary
                data URI scheme for images.
        """
        with open(image_path, "rb") as f:
            data = f.read()
            encoded = base64.b64encode(data)
        data = "data:image/png;base64," + encoded.decode("utf-8")
        return data

    @staticmethod
    def set_file_modification_time(file_path, modification_time_string):
        """
        Sets the modification time of a file based on a given time string in the California time zone.

        Args:
            file_path (str): The path to the file.
            modification_time_string (str): The desired modification time in 'YYYY-MM-DD HH:MM:SS' format.
        """
        california_tz = pytz.timezone("America/Los_Angeles")
        modification_time = datetime.datetime.strptime(
            modification_time_string, "%Y-%m-%d %H:%M:%S"
        )
        modification_time = california_tz.localize(modification_time)
        modification_time_utc = modification_time.astimezone(datetime.timezone.utc)
        modification_timestamp = modification_time_utc.timestamp()
        os.utime(file_path, (modification_timestamp, modification_timestamp))

    @staticmethod
    def get_latest_modification_time(path):
        """
        Returns the latest modification time of all files in a directory in the California time zone as a string.

        Args:
            directory_path (str): The path to the directory.

        Returns:
            str: The latest file's modification time in 'YYYY-MM-DD HH:MM:SS' format.
        """
        california_tz = pytz.timezone("America/Los_Angeles")
        latest_mod_time = None

        file_paths = []
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                for file in files:
                    file_paths.append(os.path.join(root, file))
        else:
            file_paths = [path]

        for file_path in file_paths:
            modification_timestamp = os.path.getmtime(file_path)
            modification_time_utc = datetime.datetime.utcfromtimestamp(
                modification_timestamp
            )
            modification_time_utc = modification_time_utc.replace(
                tzinfo=datetime.timezone.utc
            )
            modification_time_california = modification_time_utc.astimezone(
                california_tz
            )

            if (
                latest_mod_time is None
                or modification_time_california > latest_mod_time
            ):
                latest_mod_time = modification_time_california

        if latest_mod_time is not None:
            return latest_mod_time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def assemble_article_data(article_file_path_dict):
        """
        Constructs a dictionary containing the content and metadata of an article
        based on the available files in the article's directory. This includes the
        main article text, citations from a JSON file, and a conversation log if
        available. The function prioritizes a polished version of the article if
        both a raw and polished version exist.

        Args:
            article_file_paths (dict): A dictionary where keys are file names relevant
                                    to the article (e.g., the article text, citations
                                    in JSON format, conversation logs) and values
                                    are their corresponding file paths.

        Returns:
            dict or None: A dictionary containing the parsed content of the article,
                        citations, and conversation log if available. Returns None
                        if neither the raw nor polished article text exists in the
                        provided file paths.
        """
        if (
            "storm_gen_article.txt" in article_file_path_dict
            or "storm_gen_article_polished.txt" in article_file_path_dict
        ):
            full_article_name = (
                "storm_gen_article_polished.txt"
                if "storm_gen_article_polished.txt" in article_file_path_dict
                else "storm_gen_article.txt"
            )
            article_data = {
                "article": DemoTextProcessingHelper.parse(
                    DemoFileIOHelper.read_txt_file(
                        article_file_path_dict[full_article_name]
                    )
                )
            }
            if "url_to_info.json" in article_file_path_dict:
                article_data["citations"] = _construct_citation_dict_from_search_result(
                    DemoFileIOHelper.read_json_file(
                        article_file_path_dict["url_to_info.json"]
                    )
                )
            if "conversation_log.json" in article_file_path_dict:
                article_data["conversation_log"] = DemoFileIOHelper.read_json_file(
                    article_file_path_dict["conversation_log.json"]
                )
            return article_data
        return None


class DemoTextProcessingHelper:
    @staticmethod
    def remove_citations(sent):
        return (
            re.sub(r"\[\d+", "", re.sub(r" \[\d+", "", sent))
            .replace(" |", "")
            .replace("]", "")
        )

    @staticmethod
    def parse_conversation_history(json_data):
        """
        Given conversation log data, return list of parsed data of following format
        (persona_name, persona_description, list of dialogue turn)
        """
        parsed_data = []
        for persona_conversation_data in json_data:
            raw = persona_conversation_data["perspective"]
            # 使用 Persona.from_perspective 统一解析（兼容中英文冒号）
            p = Persona.from_perspective(raw)
            cur_conversation = []
            for dialogue_turn in persona_conversation_data["dlg_turns"]:
                cur_conversation.append(
                    {"role": "user", "content": dialogue_turn["user_utterance"]}
                )
                cur_conversation.append(
                    {
                        "role": "assistant",
                        "content": DemoTextProcessingHelper.remove_citations(
                            dialogue_turn["agent_utterance"]
                        ),
                    }
                )
            parsed_data.append((p.name, p.description, cur_conversation))
        return parsed_data

    @staticmethod
    def parse(text):
        regex = re.compile(r']:\s+"(.*?)"\s+http')
        text = regex.sub("]: http", text)
        return text

    @staticmethod
    def add_markdown_indentation(input_string):
        lines = input_string.split("\n")
        processed_lines = [""]
        for line in lines:
            num_hashes = 0
            for char in line:
                if char == "#":
                    num_hashes += 1
                else:
                    break
            num_hashes -= 1
            num_spaces = 4 * num_hashes
            new_line = " " * num_spaces + line
            processed_lines.append(new_line)
        return "\n".join(processed_lines)

    @staticmethod
    def get_current_time_string():
        """
        Returns the current time in the California time zone as a string.

        Returns:
            str: The current California time in 'YYYY-MM-DD HH:MM:SS' format.
        """
        california_tz = pytz.timezone("America/Los_Angeles")
        utc_now = datetime.datetime.now(datetime.timezone.utc)
        california_now = utc_now.astimezone(california_tz)
        return california_now.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def compare_time_strings(
        time_string1, time_string2, time_format="%Y-%m-%d %H:%M:%S"
    ):
        """
        Compares two time strings to determine if they represent the same point in time.

        Args:
            time_string1 (str): The first time string to compare.
            time_string2 (str): The second time string to compare.
            time_format (str): The format of the time strings, defaults to '%Y-%m-%d %H:%M:%S'.

        Returns:
            bool: True if the time strings represent the same time, False otherwise.
        """
        # Parse the time strings into datetime objects
        time1 = datetime.datetime.strptime(time_string1, time_format)
        time2 = datetime.datetime.strptime(time_string2, time_format)

        # Compare the datetime objects
        return time1 == time2

    @staticmethod
    def add_inline_citation_link(article_text, citation_dict):
        # Regular expression to find citations like [i]
        pattern = r"\[(\d+)\]"

        # Function to replace each citation with its Markdown link
        def replace_with_link(match):
            i = match.group(1)
            url = citation_dict.get(int(i), {}).get("url", "#")
            return f"[[{i}]]({url})"

        # Replace all citations in the text with Markdown links
        return re.sub(pattern, replace_with_link, article_text)

    @staticmethod
    def generate_html_toc(md_text):
        toc = []
        for line in md_text.splitlines():
            if line.startswith("#"):
                level = line.count("#")
                title = line.strip("# ").strip()
                anchor = title.lower().replace(" ", "-").replace(".", "")
                toc.append(
                    f"<li style='margin-left: {20 * (level - 1)}px;'><a href='#{anchor}'>{title}</a></li>"
                )
        return "<ul>" + "".join(toc) + "</ul>"

    @staticmethod
    def construct_bibliography_from_url_to_info(url_to_info):
        bibliography_list = []
        sorted_url_to_unified_index = dict(
            sorted(
                url_to_info["url_to_unified_index"].items(), key=lambda item: item[1]
            )
        )
        for url, index in sorted_url_to_unified_index.items():
            title = url_to_info["url_to_info"][url]["title"]
            bibliography_list.append(f"[{index}]: [{title}]({url})")
        bibliography_string = "\n\n".join(bibliography_list)
        return f"# References\n\n{bibliography_string}"


class DemoUIHelper:
    def st_markdown_adjust_size(content, font_size=20):
        st.markdown(
            f"""
        <span style='font-size: {font_size}px;'>{content}</span>
        """,
            unsafe_allow_html=True,
        )

    @staticmethod
    def get_article_card_UI_style(boarder_color="#9AD8E1"):
        return {
            "card": {
                "width": "100%",
                "height": "116px",
                "max-width": "640px",
                "background-color": "#FFFFF",
                "border": "1px solid #CCC",
                "padding": "20px",
                "border-radius": "5px",
                "border-left": f"0.5rem solid {boarder_color}",
                "box-shadow": "0 0.15rem 1.75rem 0 rgba(58, 59, 69, 0.15)",
                "margin": "0px",
            },
            "title": {
                "white-space": "nowrap",
                "overflow": "hidden",
                "text-overflow": "ellipsis",
                "font-size": "17px",
                "color": "rgb(49, 51, 63)",
                "text-align": "left",
                "width": "95%",
                "font-weight": "normal",
            },
            "text": {
                "white-space": "nowrap",
                "overflow": "hidden",
                "text-overflow": "ellipsis",
                "font-size": "25px",
                "color": "rgb(49, 51, 63)",
                "text-align": "left",
                "width": "95%",
            },
            "filter": {"background-color": "rgba(0, 0, 0, 0)"},
        }

    @staticmethod
    def customize_toast_css_style():
        # Note padding is top right bottom left
        st.markdown(
            """
            <style>

                div[data-testid=stToast] {
                    padding: 20px 10px 40px 10px;
                    background-color: #FF0000;   /* red */
                    width: 40%;
                }

                [data-testid=toastContainer] [data-testid=stMarkdownContainer] > p {
                    font-size: 25px;
                    font-style: normal;
                    font-weight: 400;
                    color: #FFFFFF;   /* white */
                    line-height: 1.5; /* Adjust this value as needed */
                }
            </style>
            """,
            unsafe_allow_html=True,
        )

    @staticmethod
    def article_markdown_to_html(article_title, article_content):
        return f"""
        <html>
            <head>
                <meta charset="utf-8">
                <title>{article_title}</title>
                <style>
                    .title {{
                        text-align: center;
                    }}
                </style>
            </head>
            <body>
                <div class="title">
                    <h1>{article_title.replace('_', ' ')}</h1>
                </div>
                <h2>Table of Contents</h2>
                {DemoTextProcessingHelper.generate_html_toc(article_content)}
                {markdown.markdown(article_content)}
            </body>
        </html>
        """


def _construct_citation_dict_from_search_result(search_results):
    if search_results is None:
        return None
    citation_dict = {}
    for url, index in search_results["url_to_unified_index"].items():
        citation_dict[index] = {
            "url": url,
            "title": search_results["url_to_info"][url]["title"],
            "snippets": search_results["url_to_info"][url]["snippets"],
        }
    return citation_dict


def _display_main_article_text(article_text, citation_dict, table_content_sidebar=None):
    # Post-process the generated article for better display.
    if "Write the lead section:" in article_text:
        article_text = article_text[
            article_text.find("Write the lead section:")
            + len("Write the lead section:") :
        ]
    if article_text[0] == "#":
        article_text = "\n".join(article_text.split("\n")[1:])
    article_text = DemoTextProcessingHelper.add_inline_citation_link(
        article_text, citation_dict
    )
    # '$' needs to be changed to '\$' to avoid being interpreted as LaTeX in st.markdown()
    article_text = article_text.replace("$", "\\$")
    stoc.from_markdown(article_text, table_content_sidebar)


def _display_references(citation_dict):
    if citation_dict:
        ref_titles = []
        for i in range(1, len(citation_dict) + 1):
            entry = citation_dict[i]
            title = entry.get("title", "").replace("$", "\\$")[:80]
            ref_titles.append(f"[{i}] {title}" if title else f"[{i}]")
        selected_key = st.selectbox("选择参考文献", ref_titles)
        idx = ref_titles.index(selected_key) + 1
        citation_val = citation_dict[idx]
        citation_val["title"] = citation_val["title"].replace("$", "\\$")
        st.markdown(f"**标题:** {citation_val['title']}")
        st.markdown(f"**链接:** {citation_val['url']}")
        snippets = "\n\n".join(citation_val["snippets"]).replace("$", "\\$")
        st.markdown(f"**摘要:**\n\n{snippets}")
    else:
        st.markdown("**No references available**")


def _display_persona_conversations(conversation_log):
    """
    Display persona conversation in dialogue UI
    """
    # get personas list as (persona_name, persona_description, dialogue turns list) tuple
    parsed_conversation_history = DemoTextProcessingHelper.parse_conversation_history(
        conversation_log
    )
    # construct tabs for each persona conversation
    persona_tabs = st.tabs([name for (name, _, _) in parsed_conversation_history])
    for idx, persona_tab in enumerate(persona_tabs):
        with persona_tab:
            # show persona description
            st.info(parsed_conversation_history[idx][1])
            # show user / agent utterance in dialogue UI
            for message in parsed_conversation_history[idx][2]:
                message["content"] = message["content"].replace("$", "\\$")
                # 长内容使用 expander 全文展示，默认展开
                role_label = "🧑‍💻 提问" if message["role"] == "user" else "🤖 回答"
                with st.expander(f"{role_label} ({len(message['content'])}字)", expanded=True):
                    if message["role"] == "user":
                        st.markdown(f"**{message['content']}**")
                    else:
                        st.markdown(message["content"])


def _build_toc_html(md_text: str) -> str:
    """从 Markdown 构建可点击的目录 HTML，返回 HTML 字符串。"""
    import re
    items = []
    for line in md_text.split("\n"):
        if line.startswith("#"):
            level = line.count("#")
            title = line.strip("# ").strip()
            anchor = re.sub(r'[^\w\u4e00-\u9fff]', '-', title.lower()).strip('-')
            indent = "&nbsp;" * 4 * (level - 1)
            fs = "13px" if level > 2 else "14px"
            items.append(
                f'{indent}<a href="#{anchor}" style="display:block;font-size:{fs};text-decoration:none;color:#555;padding:2px 0;">{title}</a>'
            )
    return '<div style="max-height:70vh;overflow-y:auto;">' + "\n".join(items) + "</div>"


def _markdown_to_html(md_text: str, citation_dict: dict) -> str:
    """Markdown → HTML，带锚点 ID 和可点击引用链接。"""
    import re
    import markdown as _md

    # 处理引用 [1] → 可点击链接
    def _cit_link(m):
        i = m.group(1)
        url = citation_dict.get(int(i), {}).get("url", "#") if citation_dict else "#"
        return f'<a href="{url}" target="_blank" style="color:#1a73e8;">[{i}]</a>'

    md_text = re.sub(r"\[(\d+)\]", _cit_link, md_text)
    md_text = md_text.replace("$", "\\$")
    return _md.markdown(md_text, extensions=["extra", "codehilite"])


def _display_main_article(
    selected_article_file_path_dict, show_reference=True, show_conversation=True
):
    article_data = DemoFileIOHelper.assemble_article_data(
        selected_article_file_path_dict
    )
    article_text = article_data.get("article", "")
    citation_dict = article_data.get("citations", {})

    # 去掉文章开头的 # summary 标题（避免重复显示）
    if article_text.startswith("# summary"):
        article_text = "\n".join(article_text.split("\n")[1:]).strip()
    if article_text.startswith("# Summary"):
        article_text = "\n".join(article_text.split("\n")[1:]).strip()

    # 侧边栏目录
    with st.sidebar:
        st.markdown("**📑 目录**")
        st.markdown(_build_toc_html(article_text), unsafe_allow_html=True)

    st.markdown("---")

    # 底部 Tab
    tab_article, tab_conv, tab_ref = st.tabs(["📄 文章", "💬 研究过程", "📚 参考文献"])
    with tab_article:
        st.markdown(_markdown_to_html(article_text, citation_dict), unsafe_allow_html=True)
    with tab_conv:
        if "conversation_log" in article_data:
            _display_persona_conversations(article_data["conversation_log"])
        else:
            st.info("暂无对话记录")
    with tab_ref:
        if "citations" in article_data:
            _display_references(article_data["citations"])
        else:
            st.info("暂无参考文献")


def get_demo_dir():
    return os.path.dirname(os.path.abspath(__file__))


def clear_other_page_session_state(page_index: Optional[int]):
    if page_index is None:
        keys_to_delete = [key for key in st.session_state if key.startswith("page")]
    else:
        keys_to_delete = [
            key
            for key in st.session_state
            if key.startswith("page") and f"page{page_index}" not in key
        ]
    for key in set(keys_to_delete):
        del st.session_state[key]


def set_storm_runner():
    """
    从 StormConfig 配置中心读取活跃的 LLM 和检索引擎配置，
    动态构建 STORMWikiRunner 实例。
    不写死任何提供商，完全由 ~/.storm/config.toml 驱动。
    """
    # 确保能找到 cli/config_manager（相对于 storm.py 的位置）
    _cli_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..")
    if _cli_path not in sys.path:
        sys.path.insert(0, _cli_path)
    from cli.config_manager import StormConfig

    config = StormConfig()
    current_working_dir = os.path.join(get_demo_dir(), "DEMO_WORKING_DIR")
    if not os.path.exists(current_working_dir):
        os.makedirs(current_working_dir)

    # ── 引擎参数（从 StormConfig 读取，用户可调） ──
    engine_args = STORMWikiRunnerArguments(
        output_dir=current_working_dir,
        max_conv_turn=int(config.get("system.max_conv_turn") or 3),
        max_perspective=int(config.get("system.max_perspective") or 3),
        search_top_k=int(config.get("system.search_top_k") or 3),
        retrieve_top_k=int(config.get("system.retrieve_top_k") or 5),
    )

    # ── LLM 配置（从 StormConfig 读取） ──
    llm_cfg = config.get_llm_config()
    provider = llm_cfg["provider"]
    api_key = llm_cfg["api_key"]
    api_base = llm_cfg["api_base"]
    model_name = llm_cfg["model"]
    lm_class_name = llm_cfg["lm_class"]
    temperature = llm_cfg["temperature"]
    top_p = llm_cfg["top_p"]

    # 若配置中未找到 key，尝试从 st.secrets 或环境变量读取
    if not api_key:
        env_key = os.environ.get(f"{provider.upper()}_API_KEY", "")
        api_key = env_key or st.secrets.get(f"{provider.upper()}_API_KEY", "")

    # 按需导入 LM 类
    LMClass = _import_lm_class(lm_class_name)

    # 构建各阶段 LM
    lm_kwargs = {"temperature": temperature, "top_p": top_p}
    if provider == "ollama":
        lm_kwargs["url"] = api_base
        lm_kwargs["model"] = model_name
    elif provider == "deepseek":
        lm_kwargs["api_key"] = api_key
        lm_kwargs["api_base"] = api_base
    else:
        lm_kwargs["api_key"] = api_key
        if api_base:
            lm_kwargs["api_base"] = api_base

    llm_configs = STORMWikiLMConfigs()
    try:
        llm_configs.set_conv_simulator_lm(
            LMClass(model=model_name, max_tokens=int(config.get("system.max_tokens_conv") or 1000), **lm_kwargs)
        )
        llm_configs.set_question_asker_lm(
            LMClass(model=model_name, max_tokens=int(config.get("system.max_tokens_conv") or 1000), **lm_kwargs)
        )
        llm_configs.set_outline_gen_lm(
            LMClass(model=model_name, max_tokens=int(config.get("system.max_tokens_outline") or 600), **lm_kwargs)
        )
        llm_configs.set_article_gen_lm(
            LMClass(model=model_name, max_tokens=int(config.get("system.max_tokens_article") or 1500), **lm_kwargs)
        )
        llm_configs.set_article_polish_lm(
            LMClass(model=model_name, max_tokens=int(config.get("system.max_tokens_polish") or 4000), **lm_kwargs)
        )
    except Exception as e:
        st.error(f"❌ LLM 初始化失败 ({provider}): {e}")
        st.session_state["runner"] = None
        return

    # ── 检索引擎配置（从 StormConfig 读取） ──
    rm_cfg = config.get_retriever_config()
    rm_name = rm_cfg["name"]
    rm_class_name = rm_cfg["class"]
    rm_params = rm_cfg["params"].copy()
    rm_params["k"] = engine_args.search_top_k

    RMClass = _import_rm_class(rm_class_name)
    try:
        if rm_name == "searxng":
            rm = RMClass(
                searxng_api_url=rm_params.pop("searxng_api_url"),
                searxng_api_key=rm_params.pop("searxng_api_key", None),
                k=rm_params.pop("k", engine_args.search_top_k),
                engines_academic=rm_params.pop("engines_academic", None),
                engines_chinese=rm_params.pop("engines_chinese", None),
                engines_general=rm_params.pop("engines_general", None),
            )
        elif rm_name == "duckduckgo":
            rm = RMClass(**rm_params)
        else:
            # 其他检索引擎：传参方式可能不同，尝试通用方式
            rm = RMClass(**rm_params)
    except Exception as e:
        st.error(f"❌ 检索引擎初始化失败 ({rm_name}): {e}")
        st.session_state["runner"] = None
        return

    # ── 嵌入与重排序（从 StormConfig 读取并显式注入） ──
    embed_cfg = config.get_embed_config()
    try:
        from knowledge_storm.encoder import Encoder as _StormEncoder
        encoder = _StormEncoder(
            backend=embed_cfg.get("backend"),
            api_key=embed_cfg.get("api_key"),
            api_base=embed_cfg.get("api_base"),
            model_name=embed_cfg.get("model"),
        )
    except Exception as e:
        st.warning(f"嵌入模型初始化失败，使用默认: {e}")
        encoder = None

    rerank_cfg = config.get_rerank_config()
    try:
        from knowledge_storm.reranker import Reranker as _StormReranker
        reranker = _StormReranker(
            backend=rerank_cfg.get("backend"),
            api_key=rerank_cfg.get("api_key"),
            api_base=rerank_cfg.get("api_base"),
            model_name=rerank_cfg.get("model"),
        )
    except Exception as e:
        st.warning(f"重排序模型初始化失败: {e}")
        reranker = None

    runner = STORMWikiRunner(engine_args, llm_configs, rm,
                             encoder=encoder, reranker=reranker)
    st.session_state["runner"] = runner


def display_article_page(
    selected_article_name,
    selected_article_file_path_dict,
    show_title=True,
    show_main_article=True,
):
    if show_title:
        st.markdown(
            f"<h2 style='text-align: center;'>{selected_article_name.replace('_', ' ')}</h2>",
            unsafe_allow_html=True,
        )

    if show_main_article:
        _display_main_article(selected_article_file_path_dict)


class StreamlitCallbackHandler(BaseCallbackHandler):
    def __init__(self, status_container):
        self.status_container = status_container

    def _safe_update(self, method_name, *args, **kwargs):
        """安全更新 UI，忽略后台线程调用的 RuntimeError（Streamlit 不允许从非主线程更新 UI）。
        更新后加入微秒让步，让 Streamlit 将挂起的 UI 消息刷新到浏览器，
        否则在后续阻塞操作（LLM API 调用等）期间用户看不到实时进度。"""
        try:
            getattr(self.status_container, method_name)(*args, **kwargs)
            import time
            time.sleep(0.05)
        except RuntimeError:
            pass

    def on_identify_perspective_start(self, **kwargs):
        self._safe_update("info",
            "开始识别研究该话题的不同视角..."
        )

    def on_identify_perspective_end(self, perspectives: list, **kwargs):
        # 兼容 Persona 对象和字符串
        items = []
        for p in perspectives:
            if hasattr(p, 'to_perspective'):
                items.append(p.to_perspective())
            else:
                items.append(str(p))
        perspective_list = "\n- ".join(items)
        self._safe_update("success",
            f"视角识别完成。将从以下视角开始收集信息：\n- {perspective_list}"
        )

    def on_information_gathering_start(self, **kwargs):
        self._safe_update("info", "正在浏览互联网获取信息...")

    def on_dialogue_turn_end(self, dlg_turn, **kwargs):
        urls = list(set([r.url for r in dlg_turn.search_results]))
        for url in urls:
            self._safe_update("markdown",
                f"""
                    <style>
                    .small-font {{
                        font-size: 14px;
                        margin: 0px;
                        padding: 0px;
                    }}
                    </style>
                    <div class="small-font">完成浏览 <a href="{url}" class="small-font" target="_blank">{url}</a>.</div>
                    """,
                unsafe_allow_html=True,
            )

    def on_information_gathering_end(self, **kwargs):
        self._safe_update("success", "信息收集完成。")

    def on_information_organization_start(self, **kwargs):
        self._safe_update("info", "正在将信息组织成层级大纲...")

    def on_direct_outline_generation_end(self, outline: str, **kwargs):
        self._safe_update("success", "已完成利用大语言模型的内置知识生成大纲。")

    def on_outline_refinement_end(self, outline: str, **kwargs):
        self._safe_update("success", "已完成利用收集到的信息完善大纲。")
