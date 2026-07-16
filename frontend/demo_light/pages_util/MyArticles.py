import os
import shutil
import time

import demo_util
import streamlit as st
from demo_util import DemoFileIOHelper, DemoUIHelper


def my_articles_page():
    with st.sidebar:
        if "page2_selected_my_article" in st.session_state:
            article_name = st.session_state["page2_selected_my_article"]
            with st.container(border=True):
                st.markdown(f"**当前文章**\n\n{article_name.replace('_', ' ')}")
                if st.button("🗑️ 删除此文", type="secondary", use_container_width=True):
                    article_dir = os.path.join(
                        demo_util.get_demo_dir(), "DEMO_WORKING_DIR", article_name
                    )
                    if os.path.isdir(article_dir):
                        shutil.rmtree(article_dir)
                    st.session_state.pop("page2_selected_my_article", None)
                    st.session_state.pop("page2_user_articles_file_path_dict", None)
                    st.session_state.pop("page3_write_article_state", None)
                    st.success(f"已删除「{article_name.replace('_', ' ')}」")
                    time.sleep(1)
                    st.rerun()
            st.divider()
        _, return_button_col = st.columns([2, 5])
        with return_button_col:
            if st.button(
                "← 返回列表",
                disabled="page2_selected_my_article" not in st.session_state,
            ):
                st.session_state.pop("page2_selected_my_article", None)
                st.rerun()

    if "page2_user_articles_file_path_dict" not in st.session_state:
        local_dir = os.path.join(demo_util.get_demo_dir(), "DEMO_WORKING_DIR")
        os.makedirs(local_dir, exist_ok=True)
        st.session_state["page2_user_articles_file_path_dict"] = (
            DemoFileIOHelper.read_structure_to_dict(local_dir)
        )

    articles = st.session_state.get("page2_user_articles_file_path_dict", {})

    if "page2_selected_my_article" not in st.session_state:
        if articles:
            article_names = sorted(articles.keys())
            st.caption(f"共 {len(article_names)} 篇研究")
            for name in article_names:
                with st.container(border=True):
                    c1, c2 = st.columns([4, 1])
                    with c1:
                        st.markdown(f"📄 **{name.replace('_', ' ')}**")
                    with c2:
                        if st.button("📖", key=f"view_{name}", help="查看"):
                            st.session_state["page2_selected_my_article"] = name
                            st.rerun()
        else:
            st.info("尚未生成任何研究。前往「新建论文」开始。")
    else:
        selected_article_name = st.session_state["page2_selected_my_article"]
        if selected_article_name in articles:
            selected_article_file_path_dict = articles[selected_article_name]
            demo_util.display_article_page(
                selected_article_name=selected_article_name,
                selected_article_file_path_dict=selected_article_file_path_dict,
                show_title=True,
                show_main_article=True,
            )
        else:
            st.error("文章已不存在")
            st.session_state.pop("page2_selected_my_article", None)
            st.rerun()
