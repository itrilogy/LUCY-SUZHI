import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
wiki_root_dir = os.path.dirname(os.path.dirname(script_dir))

import demo_util
from pages_util import MyArticles, CreateNewArticle, Configuration
from streamlit_float import *
from streamlit_option_menu import option_menu


# ── 全局样式 ──
st.markdown("""
<style>
    /* 卡片圆角+阴影 */
    .stCard, div[data-testid="stVerticalBlock"] > div[data-testid="column"] > div {
        border-radius: 12px !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06) !important;
        transition: box-shadow 0.2s;
    }
    .stCard:hover, div[data-testid="stVerticalBlock"] > div[data-testid="column"] > div:hover {
        box-shadow: 0 4px 16px rgba(0,0,0,0.1) !important;
    }
    /* 正文区域居中对齐 */
    .main > div:first-child {
        max-width: 960px;
        margin: 0 auto;
        padding: 1rem 2rem;
    }
    /* 侧边栏目录字体 */
    .css-1d391kg, .css-163ttbj {
        font-size: 14px;
        line-height: 1.6;
    }
    /* 标签页美化 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        border-radius: 8px 8px 0 0;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 6px 6px 0 0;
        padding: 8px 18px;
        font-weight: 500;
    }
    /* 删除按钮颜色 */
    button[kind="secondary"] {
        color: #e74c3c !important;
        border-color: #e74c3c !important;
    }
    /* 导航栏间距 */
    .nav-link {
        padding: 0.5rem 1rem;
    }
</style>""", unsafe_allow_html=True)


def main():
    global database
    st.set_page_config(layout="wide")

    if "first_run" not in st.session_state:
        st.session_state["first_run"] = True

    # set api keys from secrets (兼容旧式 st.secrets.toml)
    if st.session_state["first_run"]:
        for key, value in st.secrets.items():
            if type(value) == str:
                os.environ[key] = value

        # 同时从 StormConfig 加载密钥（~/.storm/config.toml 优先级更高）
        _cli_path = os.path.join(script_dir, "..", "..")
        if _cli_path not in sys.path:
            sys.path.insert(0, _cli_path)
        try:
            from cli.config_manager import StormConfig
            storm_config = StormConfig()
            for item in storm_config.list_all():
                if item["env_var"] and item["value"] and not os.environ.get(item["env_var"]):
                    os.environ[item["env_var"]] = item["value"]
        except ImportError:
            pass  # cli 模块不可用时不做处理

    # initialize session_state
    if "selected_article_index" not in st.session_state:
        st.session_state["selected_article_index"] = 0
    if "selected_page" not in st.session_state:
        st.session_state["selected_page"] = 0
    if st.session_state.get("rerun_requested", False):
        st.session_state["rerun_requested"] = False
        st.rerun()

    st.write(
        "<style>div.block-container{padding-top:2rem;}</style>", unsafe_allow_html=True
    )
    menu_container = st.container()
    with menu_container:
        pages = ["我的文章", "新建论文", "系统配置"]
        styles = {
            "container": {"padding": "0.2rem 0", "background-color": "#22222200"},
        }
        menu_selection = option_menu(
            None,
            pages,
            icons=["house", "search", "gear"],
            menu_icon="cast",
            default_index=0,
            orientation="horizontal",
            manual_select=st.session_state.selected_page,
            styles=styles,
            key="menu_selection",
        )
        if st.session_state.get("manual_selection_override", False):
            menu_selection = pages[st.session_state["selected_page"]]
            st.session_state["manual_selection_override"] = False
            st.session_state["selected_page"] = None

        if menu_selection == "我的文章":
            demo_util.clear_other_page_session_state(page_index=2)
            MyArticles.my_articles_page()
        elif menu_selection == "新建论文":
            demo_util.clear_other_page_session_state(page_index=3)
            CreateNewArticle.create_new_article_page()
        elif menu_selection == "系统配置":
            demo_util.clear_other_page_session_state(page_index=4)
            Configuration.config_page()


if __name__ == "__main__":
    main()
