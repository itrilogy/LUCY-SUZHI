"""https://github.com/arnaudmiribel/stoc"""

import re

import streamlit as st
import unidecode

DISABLE_LINK_CSS = """
<style>
a.toc {
    color: inherit;
    text-decoration: none; /* no underline */
}
</style>"""


class stoc:
    def __init__(self):
        self.toc_items = list()

    def h1(self, text: str, write: bool = True):
        if write:
            st.write(f"# {text}")
        self.toc_items.append(("h1", text))

    def h2(self, text: str, write: bool = True):
        if write:
            st.write(f"## {text}")
        self.toc_items.append(("h2", text))

    def h3(self, text: str, write: bool = True):
        if write:
            st.write(f"### {text}")
        self.toc_items.append(("h3", text))

    def toc(self, expander):
        st.write(DISABLE_LINK_CSS, unsafe_allow_html=True)
        if expander is None:
            expander = st.sidebar.expander("**目录**", expanded=True)
        with expander:
            with st.container(height=600, border=False):
                markdown_toc = ""
                for title_size, title in self.toc_items:
                    h = int(title_size.replace("h", ""))
                    link_id = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff_-]', '', title.lower().replace(' ', '-'))
                    markdown_toc += (
                        " " * 2 * h
                        + "- "
                        + f'<a href="#{link_id}" class="toc"> {title}</a> \n'
                    )
                st.write(markdown_toc, unsafe_allow_html=True)

        # TOC 点击时自动切换到「文章」Tab 后再定位
        st.markdown("""
<script>
document.addEventListener('click', function(e) {
    var link = e.target.closest('a.toc');
    if (link) {
        var tabs = document.querySelectorAll('[data-baseweb="tab"]');
        tabs.forEach(function(t) {
            if (t.textContent.includes('\u6587\u7ae0')) t.click();
        });
    }
});
</script>
""", unsafe_allow_html=True)

    @classmethod
    def get_toc(cls, markdown_text: str, topic=""):
        def increase_heading_depth_and_add_top_heading(markdown_text, new_top_heading):
            lines = markdown_text.splitlines()
            # Increase the depth of each heading by adding an extra '#'
            increased_depth_lines = [
                "#" + line if line.startswith("#") else line for line in lines
            ]
            # Add the new top-level heading at the beginning
            increased_depth_lines.insert(0, f"# {new_top_heading}")
            # Re-join the modified lines back into a single string
            modified_text = "\n".join(increased_depth_lines)
            return modified_text

        if topic:
            markdown_text = increase_heading_depth_and_add_top_heading(
                markdown_text, topic
            )
        toc = []
        for line in markdown_text.splitlines():
            if line.startswith("#"):
                # Remove the '#' characters and strip leading/trailing spaces
                heading_text = line.lstrip("#").strip()
                # Create slug (lowercase, spaces to hyphens, remove non-alphanumeric characters)
                slug = (
                    re.sub(r"[^a-zA-Z0-9\s-]", "", heading_text)
                    .lower()
                    .replace(" ", "-")
                )
                # Determine heading level for indentation
                level = line.count("#") - 1
                # Add to the table of contents
                toc.append("  " * level + f"- [{heading_text}](#{slug})")
        return "\n".join(toc)

    @classmethod
    def from_markdown(cls, text: str, expander=None):
        self = cls()
        # 直接用原始标题文本生成稳定的 id
        def _make_id(t):
            return re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff_-]', '', t.lower().replace(' ', '-'))

        html_lines = []
        for line in text.splitlines():
            if line.startswith("### "):
                t = line[4:].strip()
                self.toc_items.append(("h3", t))
                html_lines.append(f'<h3 id="{_make_id(t)}">{t}</h3>')
            elif line.startswith("## "):
                t = line[3:].strip()
                self.toc_items.append(("h2", t))
                html_lines.append(f'<h2 id="{_make_id(t)}">{t}</h2>')
            elif line.startswith("# "):
                t = line[2:].strip()
                self.toc_items.append(("h1", t))
                html_lines.append(f'<h1 id="{_make_id(t)}">{t}</h1>')
            else:
                html_lines.append(line)

        custom_css = """
        <style>
            h1 { font-size: 28px; } h2 { font-size: 24px; } h3 { font-size: 22px; }
            h4 { font-size: 20px; } h5 { font-size: 18px; }
            p { font-size: 18px; }
        </style>
        """
        st.markdown(custom_css + "\n".join(html_lines), unsafe_allow_html=True)
        self.toc(expander=expander)


def normalize(s):
    """
    Normalize titles as valid HTML ids for anchors
    >>> normalize("it's a test to spot how Things happ3n héhé")
    "it-s-a-test-to-spot-how-things-happ3n-h-h"
    """

    # Replace accents with "-"
    s_wo_accents = unidecode.unidecode(s)
    accents = [s for s in s if s not in s_wo_accents]
    for accent in accents:
        s = s.replace(accent, "-")

    # Lowercase
    s = s.lower()

    # Keep only alphanum and remove "-" suffix if existing
    normalized = (
        "".join([char if char.isalnum() else "-" for char in s]).strip("-").lower()
    )

    return normalized
