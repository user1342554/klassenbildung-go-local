"""Global look and feel for the Streamlit app.

Colors, fonts and radii live in ``.streamlit/config.toml`` so that Streamlit's own
widgets pick them up in light and dark mode. This module adds the layout, typography
and glass rules that the theme config cannot express. Selectors stick to
``data-testid`` attributes because Streamlit's emotion class names change between
releases.

Frosted surfaces are blur plus a flat translucent tint and a hairline edge. No
gradients: the color always comes from whatever the surface happens to sit over.

Streamlit exposes no CSS custom properties for its theme, so the tokens below are
declared twice and switched with ``prefers-color-scheme`` - the same signal Streamlit
itself uses to pick ``[theme.light]`` or ``[theme.dark]``.
"""

from __future__ import annotations

import streamlit as st

APP_STYLES = """
<style>
:root {
  --kb-glass: rgba(255, 255, 255, 0.62);
  --kb-glass-edge: rgba(255, 255, 255, 0.7);
  --kb-hairline: rgba(0, 0, 0, 0.08);
  --kb-shadow: 0 12px 36px rgba(31, 38, 74, 0.12);
}

@media (prefers-color-scheme: dark) {
  :root {
    --kb-glass: rgba(44, 44, 46, 0.7);
    --kb-glass-edge: rgba(255, 255, 255, 0.14);
    --kb-hairline: rgba(255, 255, 255, 0.12);
    --kb-shadow: 0 12px 36px rgba(0, 0, 0, 0.45);
  }
}

/* --- Glass surfaces ------------------------------------------------------ */
[data-testid="stTabs"] [role="tablist"],
[data-testid="stMetric"],
[data-testid="stExpander"] details,
[data-testid="stElementToolbar"] {
  backdrop-filter: blur(30px) saturate(180%);
  -webkit-backdrop-filter: blur(30px) saturate(180%);
  background: var(--kb-glass);
  border: 1px solid var(--kb-glass-edge);
  box-shadow: var(--kb-shadow);
}

/* --- Chrome -------------------------------------------------------------- */
/* The header holds nothing but the overflow menu, so it is dead space above
   every screen. Hiding it also frees the sticky offset the tab bar sits at. */
[data-testid="stHeader"],
[data-testid="stDecoration"],
[data-testid="stBaseButton-header"],
[data-testid="stStatusWidget"] { display: none; }

.stMainBlockContainer {
  max-width: 1360px;
  padding: 2.5rem 3rem 6rem;
}

/* --- Typography ---------------------------------------------------------- */
/* Heading sizes and weights come from [theme] in .streamlit/config.toml. */
h1, h2, h3, h4 { letter-spacing: -0.02em; }

h1 { padding: 0 0 0.75rem; }

h3 { padding: 1.5rem 0 0.35rem; }

/* The heading anchors add hover clutter to every section title. */
h1 a, h2 a, h3 a, h4 a { display: none !important; }

[data-testid="stCaptionContainer"] { opacity: 0.75; }

/* --- Tabs ---------------------------------------------------------------- */
/* The bar scrolls away with the page. Pinning it kept the steps in reach but
   left it hovering over the class board for the whole scroll. */
[data-testid="stTabs"] [role="tablist"] {
  border-radius: 14px;
  gap: 1.75rem;
  padding: 0 1.25rem;
}

[data-testid="stTabs"] [role="tab"] {
  font-size: 0.95rem;
  font-weight: 500;
  letter-spacing: -0.01em;
  padding: 0.6rem 0;
}

/* --- Controls ------------------------------------------------------------ */
[data-testid="stMetric"] {
  border-radius: 16px;
  padding: 0.9rem 1.1rem;
  transition: transform 160ms ease, box-shadow 160ms ease;
}

[data-testid="stMetric"]:hover { transform: translateY(-1px); }

[data-testid="stMetricLabel"] p {
  font-size: 0.8rem;
  letter-spacing: 0.01em;
  opacity: 0.7;
}

[data-testid="stExpander"] details { border-radius: 16px; }

[data-testid="stAlertContainer"] { border-radius: 12px; }

[data-testid="stDataFrame"] {
  border-radius: 12px;
  overflow: hidden;
}

[data-testid="stElementToolbar"] {
  border-radius: 10px;
  opacity: 0;
  transition: opacity 120ms ease;
}

[data-testid="stElementContainer"]:hover [data-testid="stElementToolbar"] { opacity: 1; }

/* --- Assignment board ---------------------------------------------------- */
/* Custom component iframes render at their intrinsic 300px width unless the
   component reports one, which would leave the class board unreadably narrow. */
iframe[title="app.assignment_board"] {
  width: 100% !important;
  border: 0;
  color-scheme: normal;
}
</style>
"""


def apply_app_styles() -> None:
    """Inject the global stylesheet once per script run."""
    st.markdown(APP_STYLES, unsafe_allow_html=True)
