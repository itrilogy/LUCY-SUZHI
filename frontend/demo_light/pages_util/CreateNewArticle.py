import os
import time

import demo_util
import streamlit as st
from demo_util import (
    DemoFileIOHelper,
    DemoTextProcessingHelper,
    DemoUIHelper,
    truncate_filename,
)


def handle_not_started():
    if st.session_state["page3_write_article_state"] == "not started":
        _, search_form_column, _ = st.columns([2, 5, 2])
        with search_form_column:
            with st.form(key="search_form"):
                # Text input for the search topic
                DemoUIHelper.st_markdown_adjust_size(
                    content="Enter the topic you want to learn in depth:", font_size=18
                )
                st.session_state["page3_topic"] = st.text_input(
                    label="page3_topic", label_visibility="collapsed"
                )
                pass_appropriateness_check = True

                # Submit button for the form
                submit_button = st.form_submit_button(label="开始研究")

                # ── 高级参数（可折叠） ──
                with st.expander("⚙️ 高级参数"):
                    from cli.config_manager import StormConfig
                    _cfg = StormConfig()
                    st.session_state["page3_max_conv_turn"] = st.number_input(
                        "每视角对话轮次", min_value=1, max_value=10, value=int(_cfg.get("system.max_conv_turn") or 3),
                        help="每个视角的模拟问答轮数，越大信息越丰富但耗时更长")
                    st.session_state["page3_max_perspective"] = st.number_input(
                        "视角数量", min_value=1, max_value=10, value=int(_cfg.get("system.max_perspective") or 3),
                        help="从不同角度研究话题的专家数量")
                    st.session_state["page3_search_top_k"] = st.number_input(
                        "每轮搜索结果数", min_value=1, max_value=10, value=int(_cfg.get("system.search_top_k") or 3),
                        help="每轮搜索返回的 top K 结果")
                # only start new search when button is clicked, not started, or already finished previous one
                if submit_button and st.session_state["page3_write_article_state"] in [
                    "not started",
                    "show results",
                ]:
                    if not st.session_state["page3_topic"].strip():
                        pass_appropriateness_check = False
                        st.session_state["page3_warning_message"] = (
                            "topic could not be empty"
                        )

                    st.session_state["page3_topic_name_cleaned"] = (
                        st.session_state["page3_topic"]
                        .replace(" ", "_")
                        .replace("/", "_")
                    )
                    st.session_state["page3_topic_name_truncated"] = truncate_filename(
                        st.session_state["page3_topic_name_cleaned"]
                    )
                    if not pass_appropriateness_check:
                        st.session_state["page3_write_article_state"] = "not started"
                        alert = st.warning(
                            st.session_state["page3_warning_message"], icon="⚠️"
                        )
                        time.sleep(5)
                        alert.empty()
                    else:
                        # 将用户调整的高级参数持久化到 config
                        _cfg = StormConfig()
                        _cfg.set("system.max_conv_turn", str(st.session_state.get("page3_max_conv_turn", 3)))
                        _cfg.set("system.max_perspective", str(st.session_state.get("page3_max_perspective", 3)))
                        _cfg.set("system.search_top_k", str(st.session_state.get("page3_search_top_k", 3)))
                        st.session_state["page3_write_article_state"] = "initiated"


def handle_initiated():
    if st.session_state["page3_write_article_state"] == "initiated":
        current_working_dir = os.path.join(demo_util.get_demo_dir(), "DEMO_WORKING_DIR")
        if not os.path.exists(current_working_dir):
            os.makedirs(current_working_dir)

        if "runner" not in st.session_state:
            demo_util.set_storm_runner()
        st.session_state["page3_current_working_dir"] = current_working_dir
        st.session_state["page3_write_article_state"] = "pre_writing"


def handle_pre_writing():
    if st.session_state["page3_write_article_state"] == "pre_writing":
        status = st.status(
            "I am brain**STORM**ing now to research the topic. (This may take 2-3 minutes.)"
        )
        st_callback_handler = demo_util.StreamlitCallbackHandler(status)
        with status:
            # STORM main gen outline
            st.session_state["runner"].run(
                topic=st.session_state["page3_topic"],
                do_research=True,
                do_generate_outline=True,
                do_generate_article=False,
                do_polish_article=False,
                callback_handler=st_callback_handler,
            )
            conversation_log_path = os.path.join(
                st.session_state["page3_current_working_dir"],
                st.session_state["page3_topic_name_truncated"],
                "conversation_log.json",
            )
            demo_util._display_persona_conversations(
                DemoFileIOHelper.read_json_file(conversation_log_path)
            )
            st.session_state["page3_write_article_state"] = "final_writing"
            status.update(label="brain**STORM**ing complete!", state="complete")


def handle_final_writing():
    if st.session_state["page3_write_article_state"] == "final_writing":
        # polish final article
        with st.status(
            "Now I will connect the information I found for your reference. (This may take 4-5 minutes.)"
        ) as status:
            st.info(
                "Now I will connect the information I found for your reference. (This may take 4-5 minutes.)"
            )
            st.session_state["runner"].run(
                topic=st.session_state["page3_topic"],
                do_research=False,
                do_generate_outline=False,
                do_generate_article=True,
                do_polish_article=True,
                remove_duplicate=False,
            )
            # finish the session
            st.session_state["runner"].post_run()

            # update status bar
            st.session_state["page3_write_article_state"] = "prepare_to_show_result"
            status.update(label="information snythesis complete!", state="complete")


def handle_prepare_to_show_result():
    if st.session_state["page3_write_article_state"] == "prepare_to_show_result":
        _, show_result_col, _ = st.columns([4, 3, 4])
        with show_result_col:
            if st.button("show final article"):
                st.session_state["page3_write_article_state"] = "completed"
                st.rerun()


def handle_completed():
    if st.session_state["page3_write_article_state"] == "completed":
        # display polished article
        current_working_dir_paths = DemoFileIOHelper.read_structure_to_dict(
            st.session_state["page3_current_working_dir"]
        )
        current_article_file_path_dict = current_working_dir_paths[
            st.session_state["page3_topic_name_truncated"]
        ]
        demo_util.display_article_page(
            selected_article_name=st.session_state["page3_topic_name_cleaned"],
            selected_article_file_path_dict=current_article_file_path_dict,
            show_title=True,
            show_main_article=True,
        )


def create_new_article_page():
    demo_util.clear_other_page_session_state(page_index=3)

    if "page3_write_article_state" not in st.session_state:
        st.session_state["page3_write_article_state"] = "not started"

    handle_not_started()

    handle_initiated()

    handle_pre_writing()

    handle_final_writing()

    handle_prepare_to_show_result()

    handle_completed()
