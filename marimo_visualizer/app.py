import marimo

__generated_with = "0.20.4"
app = marimo.App(width="full")


@app.cell
def _():
    import argparse
    import marimo as mo
    import os
    import sys
    from pathlib import Path

    from viz import build_page_controls, load_and_prepare_runs, render_page

    return Path, argparse, build_page_controls, load_and_prepare_runs, mo, os, render_page, sys


@app.cell
def _(Path, argparse, os, sys):
    PAGE_NAMES = [
        "Overview",
        "Long-Term",
        "Tour Summary",
        "Joint Tours",
        "Destination",
        "Tour TOD",
        "Tour Mode",
        "Stop Frequency",
        "Stop Location",
        "Stop Timing",
        "Trip Mode",
    ]
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", "-c")
    cli_args, _ = parser.parse_known_args(sys.argv[1:])
    configured_path = cli_args.config or os.environ.get("ACTIVITYSIM_VIZ_CONFIG")
    if configured_path:
        default_config_path = Path(configured_path).expanduser().resolve()
    else:
        default_config_path = Path(__file__).resolve().parent / "config.yaml"
    return PAGE_NAMES, configured_path, default_config_path


@app.cell
def _(PAGE_NAMES, configured_path, default_config_path, mo):
    weight_mode = mo.ui.radio(
        ["Weighted", "Unweighted"],
        value="Weighted",
        label="Weighting",
    )
    value_mode = mo.ui.radio(
        ["Percent", "Count"],
        value="Percent",
        label="Values",
    )
    page = mo.ui.dropdown(
        PAGE_NAMES,
        value=PAGE_NAMES[0],
        label="Page",
    )
    controls = mo.vstack(
        [
            mo.md("# ActivitySim Visualizer Marimo Alt"),
            mo.md(
                f"Using config path: `{default_config_path}`  \n"
                f"Configured via: `{configured_path or 'default app.py path'}`  \n"
                "Run with `uv run marimo edit app.py` or `uv run marimo run app.py`."
            ),
            mo.hstack([weight_mode, value_mode, page], widths="equal"),
        ],
        gap=1.0,
    )
    controls
    return controls, page, value_mode, weight_mode


@app.cell
def _(default_config_path, load_and_prepare_runs):
    load_error = None
    prepared_runs = None
    try:
        prepared_runs = load_and_prepare_runs(default_config_path)
    except Exception as exc:
        load_error = f"{type(exc).__name__}: {exc}"
    return load_error, prepared_runs


@app.cell
def _(mo, default_config_path, load_error, prepared_runs):
    if load_error:
        metadata = mo.md(
            "## Load Status\n"
            f"Config path: `{default_config_path}`\n\n"
            f"Load failed with:\n```text\n{load_error}\n```"
        )
    elif prepared_runs is None:
        metadata = mo.md(
            "## Load Status\n"
            f"Config path: `{default_config_path}`\n\n"
            "No prepared runs are available."
        )
    else:
        run_lines = (
            "\n".join(f"- `{label}`" for label in prepared_runs.run_labels) or "- None"
        )
        metadata = mo.md(
            f"## {prepared_runs.config.dashboard_title}\n"
            f"Config path: `{default_config_path}`\n\n"
            f"Runs loaded ({len(prepared_runs.run_labels)}):\n{run_lines}"
        )
    metadata
    return metadata


@app.cell
def _(page, value_mode, weight_mode):
    current_page = page.value or "Overview"
    value_mode_value = value_mode.value or "Percent"
    weight_mode_value = weight_mode.value or "Weighted"
    return current_page, value_mode_value, weight_mode_value


@app.cell
def _(prepared_runs, value_mode_value, weight_mode_value):
    active_config = prepared_runs.config if prepared_runs is not None else None
    if prepared_runs is None:
        selected_runs = []
        run_colors = []
    elif weight_mode_value == "Weighted":
        selected_runs = prepared_runs.weighted_runs
        run_colors = prepared_runs.config.run_colors
    else:
        selected_runs = prepared_runs.unweighted_runs
        run_colors = prepared_runs.config.run_colors

    as_percent = value_mode_value == "Percent"
    return active_config, as_percent, run_colors, selected_runs


@app.cell
def _(
    active_config,
    build_page_controls,
    current_page,
    load_error,
    mo,
    selected_runs,
):
    page_controls = None
    if not load_error and len(selected_runs) > 0 and active_config is not None:
        page_controls = build_page_controls(current_page, selected_runs, active_config, mo)
    return page_controls


@app.cell
def _(page_controls):
    page_control_values = page_controls.value if page_controls is not None else {}
    return page_control_values


@app.cell
def _(
    active_config,
    as_percent,
    current_page,
    load_error,
    mo,
    page_control_values,
    page_controls,
    render_page,
    run_colors,
    selected_runs,
):
    if load_error:
        page_content = mo.md(
            "## Active Page\n"
            f"`{current_page}` could not be rendered because data loading failed."
        )
    else:
        mo.stop(
            len(selected_runs) == 0,
            mo.md(
                "## Active Page\n"
                f"`{current_page}` is not being rendered because no runs are available."
            ),
        )
        page_content = render_page(
            page_name=current_page,
            runs=selected_runs,
            config=active_config,
            as_percent=as_percent,
            run_colors=run_colors,
            mo=mo,
            controls=page_controls,
            control_values=page_control_values,
        )

    page_content
    return page_content


if __name__ == "__main__":
    app.run()
