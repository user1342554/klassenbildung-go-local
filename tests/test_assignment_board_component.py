from pathlib import Path


COMPONENT_HTML = (
    Path(__file__).parents[1]
    / "klassenbildung"
    / "components"
    / "assignment_board"
    / "index.html"
).read_text(encoding="utf-8")

APP_STYLES = (
    Path(__file__).parents[1] / "klassenbildung" / "ui" / "theme.py"
).read_text(encoding="utf-8")


def test_assignment_board_uses_page_scrolling_instead_of_an_inner_scroller() -> None:
    assert "max-height: 720px" not in COMPONENT_HTML
    assert "overflow: auto" not in COMPONENT_HTML
    assert "table.style.minWidth" not in COMPONENT_HTML
    assert "repeat(${classCount}, minmax(0, 1fr))" in COMPONENT_HTML


def test_student_details_are_a_floating_card_with_the_app_font() -> None:
    assert 'className = "student-details-panel"' in COMPONENT_HTML
    assert 'detailGroup("Weitere Angaben", remainingFields)' in COMPONENT_HTML
    assert 'root.style.setProperty("--assignment-font", appFontFamily(theme.font))' in COMPONENT_HTML
    assert "installParentFontFaces(parentFont)" in COMPONENT_HTML
    assert 'className = "student-popover"' not in COMPONENT_HTML


def test_student_details_float_next_to_the_selected_child() -> None:
    assert "placeStudentDetails(panel, root, wrap)" in COMPONENT_HTML
    assert ".student-details-panel {" in COMPONENT_HTML
    style_block = COMPONENT_HTML.split(".student-details-panel {", 1)[1].split("}", 1)[0]
    assert "position: absolute;" in style_block


def test_the_card_lands_in_the_part_of_the_board_that_is_on_screen() -> None:
    # The board is taller than the window, so anchoring inside it is not enough.
    assert "function visibleBand(wrap)" in COMPONENT_HTML
    assert "window.frameElement" in COMPONENT_HTML
    assert "window.parent.innerHeight" in COMPONENT_HTML
    assert "const band = visibleBand(wrap);" in COMPONENT_HTML


def test_frame_height_never_depends_on_animation_frames() -> None:
    # Streamlit starts the iframe at zero height and hides inactive tabs. A frame
    # without a layout box gets no animation frames, so the board reported no height
    # and stayed invisible.
    assert "window.requestAnimationFrame(" not in COMPONENT_HTML
    assert "requestAnimationFrame(() =>" not in COMPONENT_HTML
    assert "setTimeout(setFrameHeight, 0)" in COMPONENT_HTML
    assert "watchFrameSize()" in COMPONENT_HTML
    assert "new ResizeObserver(setFrameHeight).observe(document.documentElement)" in COMPONENT_HTML


def test_notes_are_marked_across_the_whole_row_not_just_a_dot() -> None:
    assert ".assignment-student.has-note {" in COMPONENT_HTML
    row_style = COMPONENT_HTML.split(".assignment-student.has-note {", 1)[1].split("}", 1)[0]
    assert "background: var(--assignment-note);" in row_style
    assert "font-weight: 500;" in row_style


def test_secondary_student_fields_hide_behind_a_disclosure() -> None:
    # The card has to fit without scrolling, so only note, key facts and wishes show.
    assert "createDetailDisclosure(groups)" in COMPONENT_HTML
    assert 'disclosure.className = "detail-more"' in COMPONENT_HTML
    assert 'summary.textContent = "Alle Angaben"' in COMPONENT_HTML


def test_overlays_share_one_glass_recipe() -> None:
    assert ".assignment-glass {" in COMPONENT_HTML
    glass = COMPONENT_HTML.split(".assignment-glass {", 1)[1].split("}", 1)[0]
    assert "backdrop-filter: blur(30px) saturate(180%);" in glass
    assert "background: var(--assignment-glass-tint);" in glass
    assert "background: var(--kb-glass);" in APP_STYLES


def test_the_student_card_is_solid_rather_than_frosted() -> None:
    card = COMPONENT_HTML.split(".student-details-panel {", 1)[1].split("}", 1)[0]
    assert "background: var(--assignment-card-surface);" in card
    assert "backdrop-filter" not in card


def test_no_surface_uses_a_gradient() -> None:
    for source in (COMPONENT_HTML, APP_STYLES):
        for rule in source.split("\n"):
            if rule.strip().startswith(("*", "/*", "//")):
                continue
            assert "gradient(" not in rule, rule.strip()


def test_app_styles_stretch_the_board_iframe_to_the_container_width() -> None:
    # Custom component iframes fall back to their intrinsic 300px width.
    assert 'iframe[title="app.assignment_board"]' in APP_STYLES
    assert "width: 100% !important;" in APP_STYLES
