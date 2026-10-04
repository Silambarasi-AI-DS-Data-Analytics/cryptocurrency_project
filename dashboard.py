"""Streamlit dashboard for the Cryptocurrency Price Tracker.

The dashboard is strictly read-only. It visualises the records that the scraper
already stored in ``data/crypto_prices.csv`` and never writes to that file, so
running it can never damage the collected history.

No value is invented. Every number shown on screen comes from a stored record,
and a field the scraper stored as ``N/A`` stays ``N/A`` - the numeric views used
by the charts and the summary cards are parsed with the very same helpers the
rest of the project uses (:func:`validation.parse_number` and
:func:`validation.parse_percentage`).

Displayed sections:

* summary cards - coin count, latest update, top-ranked coin, highest 24h change
* latest 10 records - Rank, Coin, Symbol, Price, 24h Change, Market Cap, Timestamp
* price comparison bar chart (linear or logarithmic)
* 24h percentage change bar chart
* historical price chart driven by the sidebar coin selection

Run it with::

    streamlit run dashboard.py

If the CSV is missing, empty or unreadable the dashboard stops with a clear
message instead of a traceback.
"""

import logging
from typing import List, Optional, Tuple

import pandas as pd
import plotly.express as px
import streamlit as st

from config import (
    CSV_FILE_PATH,
    CSV_HEADERS,
    MISSING_VALUE,
    NUM_COINS_TO_EXTRACT,
    TIMESTAMP_FORMAT,
)
from csv_handler import read_historical_data
from validation import parse_number, parse_percentage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Path shown to the user, kept relative so it reads the same on every machine
DISPLAY_CSV_PATH = f"{CSV_FILE_PATH.parent.name}/{CSV_FILE_PATH.name}"

# Columns of the on-screen table, in the order the report needs them
DISPLAY_COLUMNS = ["Rank", "Coin", "Symbol", "Price", "24h Change", "Market Cap", "Timestamp"]

# Numeric helper columns added next to the raw stored text
PRICE_NUM = "Price (USD)"
CHANGE_NUM = "24h Change (%)"
CAP_NUM = "Market Cap (USD)"
DERIVED_COLUMNS = (PRICE_NUM, CHANGE_NUM, CAP_NUM)

# One consistent colour scheme for every chart and card
COLORS = {
    "accent": "#2563EB",
    "positive": "#16A34A",
    "negative": "#DC2626",
    "grid": "#E2E8F0",
    "text": "#0F172A",
    "muted": "#475569",
    "card_bg": "#F8FAFC",
}

# Error messages shown when the data cannot be used
ERROR_MISSING_FILE = (
    f"No data file found at `{DISPLAY_CSV_PATH}`.\n\n"
    "Run the tracker once to collect the first records:\n\n"
    "```\npython main.py --headless\n```"
)
ERROR_UNREADABLE = (
    f"The data file `{DISPLAY_CSV_PATH}` could not be read.\n\n"
    "The technical details were written to `logs/tracker.log`. "
    "The file is left untouched, so the history can still be repaired."
)
ERROR_NO_RECORDS = (
    f"The data file `{DISPLAY_CSV_PATH}` exists but contains no records.\n\n"
    "Only the header row is present. Run `python main.py --headless` to add data."
)
ERROR_NO_TIMESTAMPS = (
    f"The `Timestamp` column in `{DISPLAY_CSV_PATH}` could not be read as "
    f"`{TIMESTAMP_FORMAT}`.\n\n"
    "Without usable timestamps the records cannot be ordered or charted over time."
)

# Lightweight styling so the page looks report-ready in a screenshot
THEME_CSS = """
<style>
    .block-container {
        padding-top: 2.1rem;
        padding-bottom: 2.5rem;
        max-width: 1400px;
    }
    div[data-testid="stMetric"] {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 0.75rem;
        padding: 0.9rem 1.1rem;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.82rem;
        color: #475569;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.65rem;
        font-weight: 600;
        color: #0F172A;
    }
    h1, h2, h3 {
        color: #0F172A;
        letter-spacing: -0.01em;
    }
    #MainMenu, footer {
        visibility: hidden;
    }
</style>
"""

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _error_message(frame: Optional[pd.DataFrame]) -> Optional[str]:
    """
    Describe why a loaded frame cannot be used, if it cannot.

    Args:
        frame (Optional[pd.DataFrame]): Frame returned by the CSV reader, or None.

    Returns:
        Optional[str]: A user-facing message, or None when the frame is usable.
    """
    if not CSV_FILE_PATH.exists():
        return ERROR_MISSING_FILE

    if frame is None:
        return ERROR_UNREADABLE

    if frame.empty:
        return ERROR_NO_RECORDS

    missing = [header for header in CSV_HEADERS if header not in frame.columns]
    if missing:
        return (
            f"`{DISPLAY_CSV_PATH}` is missing the required column(s): "
            f"{', '.join(missing)}.\n\n"
            "Expected columns: " + ", ".join(CSV_HEADERS)
        )

    return None


def _numeric_column(text_column: str, percentage: bool = False) -> pd.Series:
    """
    Convert a stored text column into numbers for charting.

    The stored text itself is never modified; values that cannot be parsed become
    NaN so they are skipped by the charts instead of turning into a fake zero.

    Args:
        text_column (str): Name of the raw column in the CSV.
        percentage (bool): True for percentage columns such as "24h Change".

    Returns:
        pd.Series: Float values aligned with the frame.
    """
    parser = parse_percentage if percentage else parse_number
    return pd.Series(
        [parser(value) if pd.notna(value) else None for value in text_column],
        index=text_column.index,
        dtype="float64",
    )


@st.cache_data(ttl=30, show_spinner=False)
def load_records() -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    Load the stored history and add numeric helper columns.

    Returns:
        Tuple[Optional[pd.DataFrame], Optional[str]]: The enriched records and
        None, or None and a message explaining the problem. The CSV file is only
        ever read, never modified.
    """
    try:
        frame = read_historical_data()
    except Exception as error:  # Defensive: the reader already handles most cases
        logger.error(f"Dashboard could not read {CSV_FILE_PATH}: {error}")
        return None, ERROR_UNREADABLE

    problem = _error_message(frame)
    if problem is not None:
        return None, problem

    enriched = frame.copy()
    enriched[PRICE_NUM] = _numeric_column(enriched["Price"])
    enriched[CHANGE_NUM] = _numeric_column(enriched["24h Change"], percentage=True)
    enriched[CAP_NUM] = _numeric_column(enriched["Market Cap"])

    enriched["Timestamp"] = pd.to_datetime(
        enriched["Timestamp"], format=TIMESTAMP_FORMAT, errors="coerce"
    )

    if enriched["Timestamp"].isna().all():
        logger.error(f"No readable Timestamp values in {CSV_FILE_PATH}")
        return None, ERROR_NO_TIMESTAMPS

    unreadable = int(enriched["Timestamp"].isna().sum())
    if unreadable:
        logger.warning(f"Ignoring {unreadable} record(s) with an unreadable Timestamp")

    logger.info(
        f"Dashboard loaded {len(enriched)} records and "
        f"{enriched['Timestamp'].nunique()} distinct snapshots"
    )
    return enriched, None


def latest_records(
    frame: pd.DataFrame, count: int = NUM_COINS_TO_EXTRACT
) -> pd.DataFrame:
    """
    Return the most recent records, newest first.

    The scraper stores every scrape as a block of records, so the last rows of
    the file are exactly the newest snapshot. They are taken from the whole file
    rather than from one timestamp group, which keeps the result at ``count``
    records even when the newest scrape stored fewer coins than usual.

    Args:
        frame (pd.DataFrame): All stored records.
        count (int): How many records to return.

    Returns:
        pd.DataFrame: The newest ``count`` records, ordered by rank.
    """
    ordered = frame.sort_values(["Timestamp", "Rank"], kind="stable")
    return ordered.tail(count).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def format_usd(value: Optional[float]) -> str:
    """
    Format a price with just enough decimals for its size.

    Args:
        value (Optional[float]): Price in USD.

    Returns:
        str: For example "$84,656.77", "$1.48" or "$0.3357".
    """
    if value is None or pd.isna(value):
        return MISSING_VALUE
    if value >= 1:
        return f"${value:,.2f}"
    if value >= 0.01:
        return f"${value:,.4f}"
    return f"${value:,.6f}"


def format_change(value: Optional[float]) -> str:
    """
    Format a 24h change as a signed percentage.

    Args:
        value (Optional[float]): Change in percent.

    Returns:
        str: For example "+1.37%" or MISSING_VALUE.
    """
    if value is None or pd.isna(value):
        return MISSING_VALUE
    return f"{value:+.2f}%"


def format_timestamp(value: Optional[pd.Timestamp]) -> str:
    """
    Format a timestamp with the project's timestamp format.

    Args:
        value (Optional[pd.Timestamp]): Timestamp to format.

    Returns:
        str: For example "2026-10-04 07:19:30".
    """
    if value is None or pd.isna(value):
        return MISSING_VALUE
    return pd.Timestamp(value).strftime(TIMESTAMP_FORMAT)


def coin_list(frame: pd.DataFrame) -> List[str]:
    """
    List the coin names available for the historical chart.

    Args:
        frame (pd.DataFrame): All stored records.

    Returns:
        List[str]: Unique coin names, sorted alphabetically.
    """
    coins = frame["Coin"].dropna().astype(str).unique().tolist()
    return sorted(coins)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------


def _style_figure(figure, title: str, height: int, x_title: str, y_title: str = "Coin"):
    """
    Apply the shared chart styling so every chart looks the same.

    Args:
        figure: The Plotly figure to style.
        title (str): Chart title.
        height (int): Height in pixels.
        x_title (str): Label for the value axis.
        y_title (str): Label for the coin axis.

    Returns:
        The styled figure.
    """
    figure.update_layout(
        title={"text": title, "font": {"size": 17, "color": COLORS["text"]}},
        height=height,
        margin={"l": 8, "r": 24, "t": 56, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Source Sans Pro, Segoe UI, sans-serif", "color": COLORS["text"]},
        showlegend=False,
        hoverlabel={"bgcolor": "#FFFFFF", "font_size": 13},
    )
    figure.update_xaxes(
        title={"text": x_title, "font": {"size": 13, "color": COLORS["muted"]}},
        gridcolor=COLORS["grid"],
        linecolor=COLORS["grid"],
        zeroline=False,
    )
    figure.update_yaxes(
        title={"text": y_title, "font": {"size": 13, "color": COLORS["muted"]}},
        gridcolor="rgba(0,0,0,0)",
        linecolor="rgba(0,0,0,0)",
        categoryorder="array",
        autorange="reversed",
    )
    return figure


def price_bar_chart(latest: pd.DataFrame, log_scale: bool = True):
    """
    Build the bar chart comparing the prices of the latest records.

    A logarithmic scale is offered because the stored prices span several orders
    of magnitude (Bitcoin next to a sub-dollar coin), which makes the smaller
    coins invisible on a linear axis.

    Args:
        latest (pd.DataFrame): The newest records.
        log_scale (bool): Whether to use a logarithmic value axis.

    Returns:
        Optional[go.Figure]: The chart, or None when no price could be parsed.
    """
    chart_data = latest.dropna(subset=[PRICE_NUM]).sort_values(PRICE_NUM)
    if chart_data.empty:
        return None

    figure = px.bar(
        chart_data,
        x=PRICE_NUM,
        y="Coin",
        orientation="h",
        custom_data=["Symbol", "Price", CAP_NUM],
    )

    axis_title = "Price in USD"
    if log_scale:
        figure.update_xaxes(type="log")
        axis_title = "Price in USD (logarithmic scale)"

    figure.update_traces(
        marker_color=COLORS["accent"],
        text=chart_data["Price"],
        textposition="outside",
        textfont={"size": 12, "color": COLORS["muted"]},
        cliponaxis=False,
        hovertemplate=(
            "<b>%{y}</b> (%{customdata[0]})<br>"
            f"Price: %{{customdata[1]}}<br>"
            "Market Cap: %{customdata[2]}<extra></extra>"
        ),
    )

    figure.update_xaxes(range=[0, chart_data[PRICE_NUM].max() * 1.35])
    return _style_figure(
        figure, "Price comparison", max(360, 34 * len(chart_data)), axis_title
    )


def change_bar_chart(latest: pd.DataFrame):
    """
    Build the bar chart of 24h percentage changes.

    Args:
        latest (pd.DataFrame): The newest records.

    Returns:
        Optional[go.Figure]: The chart, or None when no change could be parsed.
    """
    chart_data = latest.dropna(subset=[CHANGE_NUM]).sort_values(CHANGE_NUM)
    if chart_data.empty:
        return None

    bar_colors = [
        COLORS["positive"] if value >= 0 else COLORS["negative"]
        for value in chart_data[CHANGE_NUM]
    ]

    figure = px.bar(
        chart_data,
        x=CHANGE_NUM,
        y="Coin",
        orientation="h",
        custom_data=["Symbol", "24h Change", "Price"],
    )

    figure.update_traces(
        marker_color=bar_colors,
        text=chart_data["24h Change"],
        textposition="outside",
        textfont={"size": 12, "color": COLORS["muted"]},
        cliponaxis=False,
        hovertemplate=(
            "<b>%{y}</b> (%{customdata[0]})<br>"
            "24h Change: %{customdata[1]}<br>"
            "Price: %{customdata[2]}<extra></extra>"
        ),
    )

    figure.add_hline(
        y=0,
        line_color=COLORS["muted"],
        line_width=1,
        line_dash="dot",
    )

    return _style_figure(
        figure,
        "24h percentage change",
        max(360, 34 * len(chart_data)),
        "Change over the last 24 hours (%)",
    )


def history_line_chart(frame: pd.DataFrame, coin: str):
    """
    Build the historical price chart for one coin.

    Args:
        frame (pd.DataFrame): All stored records.
        coin (str): Coin name to plot.

    Returns:
        Optional[go.Figure]: The chart, or None when the coin has no readable price.
    """
    series = (
        frame[frame["Coin"] == coin].dropna(subset=[PRICE_NUM]).sort_values("Timestamp")
    )
    if series.empty:
        return None

    figure = px.line(
        series,
        x="Timestamp",
        y=PRICE_NUM,
        markers=True,
        custom_data=["Rank", "Price", "24h Change", "Market Cap"],
    )

    figure.update_traces(
        line={"color": COLORS["accent"], "width": 2.5},
        marker={"size": 7, "color": COLORS["accent"], "line": {"width": 1.5, "color": "#FFFFFF"}},
        hovertemplate=(
            f"<b>{coin}</b><br>"
            "Time: %{x|%Y-%m-%d %H:%M:%S}<br>"
            "Price: %{customdata[1]}<br>"
            "24h Change: %{customdata[2]}<br>"
            "Market Cap: %{customdata[3]}<extra></extra>"
        ),
    )

    figure.update_layout(hovermode="x unified")
    return _style_figure(
        figure,
        f"Price history: {coin}",
        420,
        "Price in USD",
        y_title="Price in USD",
    )


# ---------------------------------------------------------------------------
# Page sections
# ---------------------------------------------------------------------------


def render_error(message: str) -> None:
    """
    Show a blocking, clearly worded message instead of a traceback.

    Args:
        message (str): The message to display.
    """
    st.title("Cryptocurrency Price Dashboard")
    st.error(message, icon="🚫")
    st.stop()


def render_header(frame: pd.DataFrame, latest: pd.DataFrame) -> None:
    """
    Render the page title and a one-line description of the dataset.

    Args:
        frame (pd.DataFrame): All stored records.
        latest (pd.DataFrame): The newest records.
    """
    snapshots = int(frame["Timestamp"].nunique())
    coin_count = latest["Coin"].nunique()

    st.title("Cryptocurrency Price Dashboard")
    st.caption(
        f"Live view of `{DISPLAY_CSV_PATH}` &nbsp;|&nbsp; "
        f"{len(frame)} stored records &nbsp;|&nbsp; "
        f"{snapshots} snapshot{'s' if snapshots != 1 else ''} &nbsp;|&nbsp; "
        f"showing the latest {coin_count} coins"
    )


def render_summary_cards(latest: pd.DataFrame) -> None:
    """
    Render the four summary cards.

    Args:
        latest (pd.DataFrame): The newest records.
    """
    coins = int(latest["Coin"].nunique())
    updated = latest["Timestamp"].max()

    ranked = latest.dropna(subset=["Rank"])
    if ranked.empty:
        top_name, top_help = MISSING_VALUE, "No rank information in the stored data"
    else:
        top_row = ranked.loc[ranked["Rank"].idxmin()]
        top_name = str(top_row["Coin"])
        top_help = (
            f"Symbol {top_row['Symbol']} · Rank #{int(top_row['Rank'])} · "
            f"Price {top_row['Price']}"
        )

    changed = latest.dropna(subset=[CHANGE_NUM])
    if changed.empty:
        change_value, change_help = MISSING_VALUE, "No 24h change stored for these records"
    else:
        best = changed.loc[changed[CHANGE_NUM].idxmax()]
        change_value = format_change(best[CHANGE_NUM])
        change_help = f"{best['Coin']} ({best['Symbol']}) · Price {best['Price']}"

    left, middle, right, far_right = st.columns(4)

    with left:
        st.metric(
            "Cryptocurrencies",
            f"{coins}",
            help="Number of distinct coins in the newest snapshot",
        )
    with middle:
        st.metric(
            "Latest update",
            format_timestamp(updated),
            help="Most recent Timestamp stored in the CSV",
        )
    with right:
        st.metric(
            "Top-ranked coin",
            top_name,
            help=top_help,
        )
    with far_right:
        st.metric(
            "Highest 24h change",
            change_value,
            help=change_help,
        )


def render_latest_table(latest: pd.DataFrame) -> None:
    """
    Render the newest records as a table.

    The stored text is shown unchanged, so the price, change and market cap read
    exactly as the scraper saved them.

    Args:
        latest (pd.DataFrame): The newest records.
    """
    st.subheader("Latest records")
    available = [column for column in DISPLAY_COLUMNS if column in latest.columns]

    st.dataframe(
        latest[available],
        hide_index=True,
        column_config={
            "Rank": st.column_config.NumberColumn("Rank", format="%d"),
            "Coin": st.column_config.TextColumn("Coin"),
            "Symbol": st.column_config.TextColumn("Symbol"),
            "Price": st.column_config.TextColumn("Price"),
            "24h Change": st.column_config.TextColumn("24h Change"),
            "Market Cap": st.column_config.TextColumn("Market Cap"),
            "Timestamp": st.column_config.TextColumn("Timestamp"),
        },
    )


def render_price_charts(latest: pd.DataFrame, log_scale: bool) -> None:
    """
    Render the price and 24h change charts side by side.

    Args:
        latest (pd.DataFrame): The newest records.
        log_scale (bool): Whether the price chart uses a logarithmic axis.
    """
    left, right = st.columns(2)

    with left:
        st.subheader("Price comparison")
        price_chart = price_bar_chart(latest, log_scale=log_scale)
        if price_chart is None:
            st.info("No numeric price is stored for the latest records.")
        else:
            st.plotly_chart(price_chart)

    with right:
        st.subheader("24h change")
        change_chart = change_bar_chart(latest)
        if change_chart is None:
            st.info("No numeric 24h change is stored for the latest records.")
        else:
            st.plotly_chart(change_chart)


def render_history_section(frame: pd.DataFrame, coin: Optional[str]) -> None:
    """
    Render the historical price chart for the selected coin.

    Args:
        frame (pd.DataFrame): All stored records.
        coin (Optional[str]): Coin selected in the sidebar.
    """
    st.subheader("Historical price chart")

    if coin is None:
        st.info("Select a cryptocurrency in the sidebar to see its price history.")
        return

    history = frame[frame["Coin"] == coin].dropna(subset=["Timestamp"])
    chart = history_line_chart(frame, coin)

    if chart is None:
        st.info(f"No numeric price is stored for {coin}.")
        return

    prices = history[PRICE_NUM].dropna()
    if len(prices):
        first_price, last_price = prices.iloc[0], prices.iloc[-1]
        movement = (
            f"{(last_price - first_price) / first_price * 100:+.2f}%"
            if first_price
            else MISSING_VALUE
        )
        st.caption(
            f"{coin}: {len(prices)} snapshot{'s' if len(prices) != 1 else ''} · "
            f"lowest {format_usd(prices.min())} · "
            f"average {format_usd(prices.mean())} · "
            f"highest {format_usd(prices.max())} · "
            f"first to last {movement}"
        )
    else:
        st.caption(f"{coin}: no readable price in the stored history.")

    st.plotly_chart(chart)

    if len(prices) < 2:
        st.info(
            f"Only {len(prices)} snapshot is stored for {coin}, so the line cannot "
            "show a trend yet. Run the tracker again to collect more history."
        )


def render_data_section(frame: pd.DataFrame) -> None:
    """
    Render the full stored history in a collapsed section.

    Args:
        frame (pd.DataFrame): All stored records.
    """
    with st.expander("Full stored history (all records)"):
        st.caption(
            f"{len(frame)} records read from `{DISPLAY_CSV_PATH}`. "
            "This section is collapsed by default; the values are exactly as stored."
        )
        available = [column for column in DISPLAY_COLUMNS if column in frame.columns]
        st.dataframe(frame[available], hide_index=True)


def render_sidebar(frame: pd.DataFrame, latest: pd.DataFrame) -> Tuple[Optional[str], bool]:
    """
    Render the sidebar and return the current selections.

    Args:
        frame (pd.DataFrame): All stored records.
        latest (pd.DataFrame): The newest records.

    Returns:
        Tuple[Optional[str], bool]: The selected coin and the price scale choice.
    """
    coins = coin_list(frame)
    ranked = latest.dropna(subset=["Rank"])
    default_index = 0
    if not ranked.empty:
        default_coin = str(ranked.loc[ranked["Rank"].idxmin()]["Coin"])
        if default_coin in coins:
            default_index = coins.index(default_coin)

    with st.sidebar:
        st.header("Controls")

        selected = st.selectbox(
            "Cryptocurrency for the history chart",
            options=coins,
            index=default_index,
            format_func=lambda name: f"{name}",
            help="The historical chart plots every stored snapshot of this coin",
        )

        scale = st.radio(
            "Price chart scale",
            options=["Logarithmic", "Linear"],
            index=0,
            help=(
                "Logarithmic keeps small coins visible next to Bitcoin; "
                "Linear shows the absolute price difference."
            ),
        )

        st.divider()
        st.header("Dataset")
        st.markdown(
            f"- Source: `{DISPLAY_CSV_PATH}`\n"
            f"- Records: {len(frame)}\n"
            f"- Snapshots: {int(frame['Timestamp'].nunique())}\n"
            f"- Coins tracked: {len(coins)}\n"
            f"- Last update: {format_timestamp(frame['Timestamp'].max())}"
        )

        if st.button("Refresh data", width="stretch"):
            load_records.clear()
            st.rerun()

    return selected, scale == "Logarithmic"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """
    Build the whole dashboard page.
    """
    st.set_page_config(
        page_title="Cryptocurrency Price Dashboard",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(THEME_CSS, unsafe_allow_html=True)

    frame, problem = load_records()
    if problem is not None:
        render_error(problem)
        return

    latest = latest_records(frame)

    render_header(frame, latest)
    selected_coin, log_scale = render_sidebar(frame, latest)

    st.markdown("")

    render_summary_cards(latest)
    st.divider()
    render_latest_table(latest)
    st.divider()
    render_price_charts(latest, log_scale=log_scale)
    st.divider()
    render_history_section(frame, selected_coin)
    st.divider()
    render_data_section(frame)

    st.caption(
        "Read-only view of the data collected by the Cryptocurrency Price Tracker. "
        f"Values come straight from `{DISPLAY_CSV_PATH}`."
    )


if __name__ == "__main__":
    main()
