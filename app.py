import base64
import copy
import io
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from models.trip import Trip
from models.cost_item import CostItem, CostType, normalize_cost_type
from models.traveller import Traveller
from models.options import Option
from models.accommodation import Accommodation, RoomType
from services.calculator import (
    calculateTripTotals,
    calculateTravellerBreakdown,
    calculateCategoryTotals,
    format_currency,
)
from services.storage import (
    delete_trip,
    load_all_trips,
    load_last_open_trip_name,
    save_trip,
    set_last_open_trip,
    trip_exists,
)
from services.currency import UPDATED_AT_KEY, convert, fetch_exchange_rates
from services.visual_design import calculate_trip_progress

if get_script_run_ctx(suppress_warning=True) is None:
    app_path = Path(__file__).resolve()
    command = [sys.executable, "-m", "streamlit", "run", str(app_path)]
    if len(sys.argv) > 1:
        command.append("--")
        command.extend(sys.argv[1:])

    process = subprocess.Popen(command)
    try:
        raise SystemExit(process.wait())
    except KeyboardInterrupt:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
        raise SystemExit(130)

st.set_page_config(page_title="Luco Trip Planner", layout="wide")

st.markdown("""
<style>
.app-title {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin: 0.25rem 0 1rem;
}
.app-title img {
    height: 2.75rem;
    width: auto;
    object-fit: contain;
}
.app-title h1 {
    margin: 0;
    padding: 0;
    font-size: 2.75rem;
    line-height: 1.2;
    font-weight: 700;
}
@media (prefers-color-scheme: dark) {
    .app-title img {
        filter: invert(1);
    }
}
.delete-button-container button {
    background-color: #ff4b4b !important;
    color: white !important;
    border: none !important;
}
.delete-button-container button:hover {
    background-color: #ff3333 !important;
}
</style>
""", unsafe_allow_html=True)

NEW_TRIP_BASE_NAME = "New Trip"
CURRENCIES = ["GBP", "EUR", "USD", "AUD", "CAD", "JPY"]
COMMON_CATEGORIES = [
    "Flights",
    "Accommodation",
    "Equipment",
    "Food",
    "Transport",
    "Activities",
    "Insurance",
    "Misc",
]
TABS = ["Trip Setup", "Cost Items", "Accommodation", "Options", "Travellers", "Summary", "Notes"]
TRIP_SCOPED_WIDGET_PREFIXES = (
    "accom_total_cost_",
    "accom_currency_",
    "accom_deposit_ratio_",
    "travellers_table_",
    "bulk_assignment_",
    "bulk_traveller_",
    "traveller_name_",
    "traveller_options_",
    "traveller_room_",
)
ENTRY_DIALOG_KEY = "_entry_dialog"
ENTRY_NOTICE_KEY = "_entry_notice"
CONFIRM_ACTION_KEY = "_confirm_action"
TRIP_NAME_INPUT_KEY = "trip_name_input"
TRIP_NAME_INPUT_RENDERED_KEY = "_trip_name_input_rendered"
TRIP_NAME_INPUT_PENDING_KEY = "_pending_trip_name_input"
LOGO_PATH = Path(__file__).resolve().parent / "logo.png"

st.session_state[TRIP_NAME_INPUT_RENDERED_KEY] = False
if TRIP_NAME_INPUT_PENDING_KEY in st.session_state:
    st.session_state[TRIP_NAME_INPUT_KEY] = st.session_state.pop(TRIP_NAME_INPUT_PENDING_KEY)


def get_next_trip_name(existing_names, base_name=NEW_TRIP_BASE_NAME):
    if base_name not in existing_names:
        return base_name

    index = 1
    while True:
        candidate = f"{base_name} {index}"
        if candidate not in existing_names:
            return candidate
        index += 1


def create_new_trip():
    all_trips = load_all_trips()
    new_name = get_next_trip_name(all_trips)
    new_trip = Trip(new_name, "")
    save_trip(new_trip, new_name)
    return new_name, new_trip


def sync_trip_name_input(value):
    if st.session_state.get(TRIP_NAME_INPUT_RENDERED_KEY):
        st.session_state[TRIP_NAME_INPUT_PENDING_KEY] = value
    else:
        st.session_state[TRIP_NAME_INPUT_KEY] = value


def clear_widget_state_by_prefix(*prefixes):
    keys_to_clear = [
        key
        for key in st.session_state
        if any(key.startswith(prefix) for prefix in prefixes)
    ]
    for key in keys_to_clear:
        del st.session_state[key]


def clear_trip_scoped_widget_state():
    clear_widget_state_by_prefix(*TRIP_SCOPED_WIDGET_PREFIXES)


def switch_to_trip(trip_name, trip):
    if st.session_state.get("trip_name") != trip_name:
        clear_trip_scoped_widget_state()
    st.session_state.trip = trip
    st.session_state.trip_name = trip_name
    sync_trip_name_input(trip.name)
    set_last_open_trip(trip_name)


def render_app_header():
    if not LOGO_PATH.exists():
        st.title("Luco Trip Planner")
        return

    logo_data = base64.b64encode(LOGO_PATH.read_bytes()).decode("utf-8")
    st.markdown(
        f"""
        <div class="app-title">
            <img src="data:image/png;base64,{logo_data}" alt="Luco Trip Planner logo">
            <h1>Luco Trip Planner</h1>
        </div>
        """,
        unsafe_allow_html=True,
    )


# Initialize session state
if "trip" not in st.session_state:
    # Load the last opened trip, otherwise create the same blank trip as the New Trip button.
    all_trips = load_all_trips()
    if all_trips:
        last_open_trip_name = load_last_open_trip_name()
        trip_name = (
            last_open_trip_name
            if last_open_trip_name in all_trips
            else next(iter(all_trips))
        )
        switch_to_trip(trip_name, all_trips[trip_name])
    else:
        new_name, new_trip = create_new_trip()
        switch_to_trip(new_name, new_trip)

if "trip_name" not in st.session_state:
    st.session_state.trip_name = st.session_state.trip.name

if TRIP_NAME_INPUT_KEY not in st.session_state:
    st.session_state[TRIP_NAME_INPUT_KEY] = st.session_state.trip.name

trip = st.session_state.trip

currencies = list(CURRENCIES)
if trip.baseCurrency and trip.baseCurrency not in currencies:
    currencies = [trip.baseCurrency] + currencies

cost_type_options = list(CostType)


def get_effective_trip_name():
    return trip.name.strip() or NEW_TRIP_BASE_NAME


def persist_trip():
    if not trip.name.strip():
        return

    current_name = get_effective_trip_name()
    old_name = st.session_state.get("trip_name")

    if old_name and old_name != current_name and trip_exists(old_name):
        delete_trip(old_name)

    save_trip(trip, current_name)
    st.session_state.trip_name = current_name


def build_currency_set(trip):
    currency_set = {trip.baseCurrency}
    for item in trip.costItems:
        currency_set.add(item.currency)
    for option in trip.options:
        currency_set.add(option.currency)
    if trip.accommodation:
        currency_set.add(trip.accommodation.currency)
    return currency_set


def parse_trip_date(value):
    if not value:
        return None

    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def format_percent(value):
    return f"{value:.0%}"


def format_rate_snapshot_status(trip):
    updated_at = trip.exchangeRates.get(UPDATED_AT_KEY) if trip.exchangeRates else None
    if not updated_at:
        return "Using fallback exchange rates. Refresh when you want a saved live snapshot."

    try:
        updated = datetime.fromisoformat(updated_at)
        updated_label = updated.strftime("%d %b %Y, %H:%M")
    except ValueError:
        updated_label = "saved previously"

    rate_count = sum(
        1 for key in trip.exchangeRates if "_" in key and not key.startswith("_")
    )
    return f"Using saved exchange-rate snapshot from {updated_label} ({rate_count} rates)."


def trip_date_validation_message(trip):
    start = parse_trip_date(trip.startDate)
    end = parse_trip_date(trip.endDate)
    if start and end and end < start:
        return "End date is before the start date."
    return None


def room_type_capacity(room):
    return room.roomCount * room.bedsPerRoom


def get_room_type_assignment_counts(trip):
    if not trip.accommodation:
        return {}

    counts = {room_name: 0 for room_name in trip.accommodation.roomTypes}
    for traveller in trip.travellers:
        if traveller.roomType in counts:
            counts[traveller.roomType] += 1
    return counts


def room_type_display_label(trip, room_type_name):
    if not room_type_name:
        return "No room type"
    if not trip.accommodation:
        return room_type_name

    room = trip.accommodation.roomTypes.get(room_type_name)
    if not room:
        return room_type_name

    assigned_count = get_room_type_assignment_counts(trip).get(room_type_name, 0)
    capacity = room_type_capacity(room)
    price = trip.accommodation.room_cost(room_type_name)
    return (
        f"{room_type_name} ({assigned_count}/{capacity}) - "
        f"{format_currency(price, trip.accommodation.currency)}"
    )


def available_room_type_options(trip, current_room_type=""):
    if not trip.accommodation:
        return [""]

    assignment_counts = get_room_type_assignment_counts(trip)
    available = [""]
    for room_name, room in trip.accommodation.roomTypes.items():
        assigned_count = assignment_counts.get(room_name, 0)
        is_current_selection = room_name == current_room_type
        if is_current_selection or assigned_count < room_type_capacity(room):
            available.append(room_name)
    return available


def rename_option(trip, old_name, new_name):
    if old_name == new_name:
        return

    for traveller in trip.travellers:
        traveller.selectedOptions = [
            new_name if option_name == old_name else option_name
            for option_name in traveller.selectedOptions
        ]
    clear_widget_state_by_prefix("traveller_options_")


def rename_room_type(trip, old_name, new_name):
    if not trip.accommodation or old_name == new_name:
        return

    room = trip.accommodation.roomTypes.pop(old_name)
    room.name = new_name
    trip.accommodation.roomTypes[new_name] = room
    for traveller in trip.travellers:
        if traveller.roomType == old_name:
            traveller.roomType = new_name
    clear_widget_state_by_prefix("traveller_room_")


def clear_room_type_assignments(trip, room_name):
    for traveller in trip.travellers:
        if traveller.roomType == room_name:
            traveller.roomType = ""
    clear_widget_state_by_prefix("traveller_room_")


def cost_type_label(cost_type):
    return cost_type.name.replace("_", " ").title()


def discounted_cost_item_amount(cost_item):
    return cost_item.amount * (1 - cost_item.discountRatio)


def cost_item_total_amount(cost_item, traveller_count):
    discounted = discounted_cost_item_amount(cost_item)
    if normalize_cost_type(cost_item.costType) == CostType.PER_PERSON:
        return discounted * traveller_count
    return discounted


def cost_item_expander_label(cost_item, idx, traveller_count):
    name = cost_item.name or f"Cost Item {idx + 1}"
    total = cost_item_total_amount(cost_item, traveller_count)
    return f"{name} - {format_currency(total, cost_item.currency)}"


def option_expander_label(option, idx):
    name = option.name or f"Option {idx + 1}"
    return f"{name} - {format_currency(option.cost, option.currency)}"


def traveller_expander_label(traveller, idx, trip):
    name = traveller.name or f"Traveller {idx + 1}"
    total = calculateTravellerBreakdown(traveller, trip, convert)["total"]
    return f"{name} - {format_currency(total, trip.baseCurrency)}"


def selected_currency_index(currency, fallback_currency=None):
    if currency in currencies:
        return currencies.index(currency)
    if fallback_currency in currencies:
        return currencies.index(fallback_currency)
    return 0


def option_names(trip):
    return [option.name for option in trip.options]


def trip_widget_key(name):
    trip_name = st.session_state.get("trip_name", NEW_TRIP_BASE_NAME)
    safe_trip_name = re.sub(r"[^a-zA-Z0-9_]+", "_", trip_name).strip("_")
    return f"{name}_{safe_trip_name}"


def show_dataframe(rows, empty_message, column_config=None):
    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            width="stretch",
            column_config=column_config,
        )
    elif empty_message:
        st.info(empty_message)


def render_planning_progress(trip):
    progress = calculate_trip_progress(trip)

    st.subheader("Planning Progress")
    st.caption(f"{progress['completed']} of {progress['total']} planning items complete")
    st.progress(progress["percentage"] / 100)
    if progress["missing_items"]:
        missing_rows = [
            {
                "Item": item["field_name"],
                "Where": item["tab_name"],
                "Why it helps": item["description"],
            }
            for item in progress["missing_items"].values()
        ]
        show_dataframe(missing_rows, "")
    else:
        st.success("This trip has the core planning details filled in.")


def render_confirmed_button(action_id, label, confirm_label, on_confirm, disabled=False):
    if st.button(label, key=f"start_{action_id}", width="stretch", disabled=disabled):
        st.session_state[CONFIRM_ACTION_KEY] = action_id
        st.rerun()

    if st.session_state.get(CONFIRM_ACTION_KEY) != action_id:
        return

    st.warning(f"Confirm: {label}?")
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if st.button(confirm_label, key=f"confirm_{action_id}", type="primary", width="stretch"):
            st.session_state[CONFIRM_ACTION_KEY] = None
            on_confirm()
            st.rerun()
    with cancel_col:
        if st.button("Cancel", key=f"cancel_{action_id}", width="stretch"):
            st.session_state[CONFIRM_ACTION_KEY] = None
            st.rerun()


def open_entry_dialog(dialog_name):
    st.session_state[ENTRY_DIALOG_KEY] = dialog_name
    st.rerun()


def clear_entry_dialog():
    st.session_state[ENTRY_DIALOG_KEY] = None


def close_entry_dialog(dialog_name, success_message=None):
    clear_entry_dialog()
    if success_message:
        st.session_state[ENTRY_NOTICE_KEY] = {
            "dialog_name": dialog_name,
            "message": success_message,
        }
    persist_trip()
    st.rerun()


def show_entry_notice(dialog_name):
    notice = st.session_state.pop(ENTRY_NOTICE_KEY, None)
    if not notice:
        return

    if notice["dialog_name"] == dialog_name:
        st.success(notice["message"])
    else:
        st.session_state[ENTRY_NOTICE_KEY] = notice


def validate_trip(trip):
    errors = []
    date_message = trip_date_validation_message(trip)
    if date_message:
        errors.append(date_message)

    accommodation = trip.accommodation
    if any(traveller.roomType for traveller in trip.travellers) and not accommodation:
        errors.append(
            "Some travellers have room types selected but no accommodation is configured."
        )

    if not accommodation:
        return errors

    if not accommodation.roomTypes:
        errors.append("Accommodation is configured but no room types are defined.")

    if accommodation.totalCost > 0:
        assigned_travellers = sum(1 for traveller in trip.travellers if traveller.roomType)
        if assigned_travellers < len(trip.travellers):
            errors.append(
                "Accommodation configured but only "
                f"{assigned_travellers}/{len(trip.travellers)} travellers have "
                "room types assigned."
            )

        assignment_counts = get_room_type_assignment_counts(trip)
        for room_name, assigned_count in assignment_counts.items():
            capacity = room_type_capacity(accommodation.roomTypes[room_name])
            if assigned_count > capacity:
                errors.append(f"{room_name} is over capacity ({assigned_count}/{capacity}).")

    return errors


def build_traveller_summary_rows(trip, traveller_breakdowns):
    return [
        {
            "Name": traveller.name,
            "Total": format_currency(breakdown["total"], trip.baseCurrency),
            "Deposit": format_currency(breakdown["deposit"], trip.baseCurrency),
            "Outstanding": format_currency(
                breakdown["total"] - breakdown["deposit"],
                trip.baseCurrency,
            ),
            "Room Type": breakdown["roomType"] or "None",
            "Options": ", ".join(breakdown["selectedOptions"]) or "None",
        }
        for traveller, breakdown in traveller_breakdowns
    ]


def build_traveller_export_rows(trip):
    rows = []
    for traveller in trip.travellers:
        breakdown = calculateTravellerBreakdown(traveller, trip, convert)
        rows.append(
            {
                "Name": traveller.name,
                "Total": breakdown["total"],
                "Deposit": breakdown["deposit"],
                "Outstanding": breakdown["total"] - breakdown["deposit"],
                "Room Type": breakdown["roomType"] or "None",
                "Options": ", ".join(breakdown["selectedOptions"]),
            }
        )
    return rows


@st.dialog("Add cost item", on_dismiss=clear_entry_dialog)
def add_cost_item_dialog():
    with st.form("add_cost_item_dialog_form"):
        form_col1, form_col2 = st.columns([2, 1])
        with form_col1:
            name = st.text_input("Cost item name")
            category = st.selectbox("Category", trip.categories)
            ctype = st.selectbox(
                "Cost type",
                cost_type_options,
                format_func=cost_type_label,
            )
        with form_col2:
            amount = st.number_input("Amount", min_value=0.0, format="%.2f")
            currency = st.selectbox(
                "Currency",
                currencies,
                index=selected_currency_index(trip.baseCurrency),
            )
            deposit_ratio = st.slider(
                "Deposit ratio",
                min_value=0.0,
                max_value=1.0,
                value=0.0,
                step=0.01,
            )
            discount_ratio = st.slider(
                "Discount ratio",
                min_value=0.0,
                max_value=1.0,
                value=0.0,
                step=0.01,
            )

        submitted = st.form_submit_button("Add cost item", width="stretch")
        if submitted:
            if not name.strip():
                st.warning("Please provide a name for the cost item.")
                return

            trip.costItems.append(
                CostItem(
                    name=name.strip(),
                    category=category,
                    amount=amount,
                    currency=currency,
                    costType=ctype,
                    depositRatio=deposit_ratio,
                    discountRatio=discount_ratio,
                )
            )
            close_entry_dialog("cost_item", f"Added {name.strip()}")


@st.dialog("Add room type", on_dismiss=clear_entry_dialog)
def add_room_type_dialog():
    with st.form("add_room_type_dialog_form"):
        room_name = st.text_input("Room type name (e.g. Private, Twin, Bunk)")
        room_count = st.number_input("Number of rooms", min_value=1, value=1)
        beds_per_room = st.number_input("Beds per room", min_value=1, value=1)
        weighting = st.number_input(
            "Weight",
            min_value=0.1,
            value=1.0,
            format="%.2f",
            help="Multiplier for base cost per bed",
        )

        submitted = st.form_submit_button("Add room type", width="stretch")
        if submitted:
            normalized_room_name = room_name.strip()
            if not normalized_room_name:
                st.warning("Please provide a room type name.")
                return
            if normalized_room_name in trip.accommodation.roomTypes:
                st.warning("Room type already exists.")
                return

            trip.accommodation.roomTypes[normalized_room_name] = RoomType(
                normalized_room_name,
                room_count,
                beds_per_room,
                weighting,
            )
            close_entry_dialog("room_type", f"Added {normalized_room_name}")


@st.dialog("Add option", on_dismiss=clear_entry_dialog)
def add_option_dialog():
    with st.form("add_option_dialog_form"):
        option_col1, option_col2 = st.columns([2, 1])
        with option_col1:
            option_name = st.text_input("Option name")
        with option_col2:
            option_cost = st.number_input("Option cost", min_value=0.0, format="%.2f")
            option_currency = st.selectbox(
                "Currency",
                currencies,
                index=selected_currency_index(trip.baseCurrency),
            )
            option_deposit_ratio = st.slider(
                "Deposit ratio",
                min_value=0.0,
                max_value=1.0,
                value=1.0,
                step=0.01,
            )

        submitted = st.form_submit_button("Add option", width="stretch")
        if submitted:
            normalized_option_name = option_name.strip()
            if not normalized_option_name:
                st.warning("Please provide an option name.")
                return
            if normalized_option_name in option_names(trip):
                st.warning("Option already exists.")
                return

            trip.options.append(
                Option(
                    normalized_option_name,
                    option_cost,
                    option_currency,
                    option_deposit_ratio,
                )
            )
            close_entry_dialog("option", f"Added option: {normalized_option_name}")


@st.dialog("Add traveller", on_dismiss=clear_entry_dialog)
def add_traveller_dialog():
    with st.form("add_traveller_dialog_form"):
        traveller_name = st.text_input("Traveller name")

        available_option_names = option_names(trip)
        if trip.options:
            selected_options = st.multiselect(
                "Selected options",
                available_option_names,
                key="new_traveller_selected_options",
            )
        else:
            st.info(
                "No options available yet. Add options first if you want to assign them "
                "to the traveller."
            )
            selected_options = []

        if trip.accommodation:
            room_keys = available_room_type_options(trip)
            selected_room_type = st.selectbox(
                "Room type",
                room_keys,
                format_func=lambda room_name: room_type_display_label(trip, room_name),
                key="new_traveller_room_type",
            )
            if len(room_keys) == 1 and trip.accommodation.roomTypes:
                st.info("All room types are fully assigned.")
        else:
            selected_room_type = ""

        submitted = st.form_submit_button("Add traveller", width="stretch")
        if submitted:
            normalized_traveller_name = traveller_name.strip()
            if not normalized_traveller_name:
                st.warning("Enter a traveller name.")
                return

            trip.travellers.append(
                Traveller(
                    normalized_traveller_name,
                    selectedOptions=selected_options,
                    roomType=selected_room_type,
                )
            )
            close_entry_dialog("traveller", f"Added traveller {normalized_traveller_name}")


@st.dialog("Bulk add travellers", on_dismiss=clear_entry_dialog)
def bulk_add_travellers_dialog():
    with st.form("bulk_add_travellers_dialog_form"):
        names = st.text_area(
            "Traveller names",
            height=180,
            placeholder="One name per line",
        )
        selected_options = []
        if trip.options:
            selected_options = st.multiselect(
                "Apply options to all new travellers",
                option_names(trip),
                key="bulk_traveller_selected_options",
            )

        submitted = st.form_submit_button("Add travellers", width="stretch")
        if submitted:
            new_names = [name.strip() for name in names.splitlines() if name.strip()]
            if not new_names:
                st.warning("Enter at least one traveller name.")
                return

            existing_names = {traveller.name for traveller in trip.travellers}
            added_names = []
            skipped_names = []
            for new_name in new_names:
                if new_name in existing_names:
                    skipped_names.append(new_name)
                    continue
                trip.travellers.append(
                    Traveller(new_name, selectedOptions=list(selected_options), roomType="")
                )
                existing_names.add(new_name)
                added_names.append(new_name)

            if not added_names:
                st.warning("No new travellers were added because those names already exist.")
                return

            message = f"Added {len(added_names)} traveller(s)"
            if skipped_names:
                message += f"; skipped duplicates: {', '.join(skipped_names)}"
            close_entry_dialog("traveller", message)


render_app_header()

tabs = st.tabs(TABS)

with tabs[0]:
    st.header("Trip Setup")

    col1, col2 = st.columns([3, 1])

    with col1:
        all_trips = load_all_trips()
        trip_names = list(all_trips)

        if trip_names and st.session_state.trip_name in trip_names:
            current_index = trip_names.index(st.session_state.trip_name)
            selected_trip = st.selectbox(
                "Load trip",
                trip_names,
                index=current_index,
            )
            if selected_trip != st.session_state.trip_name:
                switch_to_trip(selected_trip, all_trips[selected_trip])
                st.rerun()
        else:
            st.info("No saved trips. Click 'New Trip' to create one.")

    with col2:
        st.markdown("<div style='height: 1.75rem;'></div>", unsafe_allow_html=True)
        if st.button("New Trip", width="stretch"):
            new_name, new_trip = create_new_trip()
            switch_to_trip(new_name, new_trip)
            st.rerun()

    st.divider()

    st.subheader("Trip Details")
    detail_col1, detail_col2 = st.columns([2, 1])
    with detail_col1:
        trip_name_input = st.text_input(
            "Trip Name",
            key=TRIP_NAME_INPUT_KEY,
        )
        st.session_state[TRIP_NAME_INPUT_RENDERED_KEY] = True
    with detail_col2:
        trip.baseCurrency = st.selectbox(
            "Base Currency",
            currencies,
            index=selected_currency_index(trip.baseCurrency),
        )
    trip.name = trip_name_input
    if trip.name.strip() and trip.name != st.session_state.trip_name:
        persist_trip()
        st.rerun()

    trip.description = st.text_area("Description", trip.description, height=120)
    date_col1, date_col2 = st.columns(2)
    with date_col1:
        start_date = st.date_input(
            "Start Date",
            value=parse_trip_date(trip.startDate),
            format="DD/MM/YYYY",
        )
    with date_col2:
        end_date = st.date_input(
            "End Date",
            value=parse_trip_date(trip.endDate),
            format="DD/MM/YYYY",
        )
    trip.startDate = start_date.isoformat() if start_date else ""
    trip.endDate = end_date.isoformat() if end_date else ""
    date_message = trip_date_validation_message(trip)
    if date_message:
        st.warning(date_message)

    used_currencies = build_currency_set(trip)
    meta_col1, meta_col2 = st.columns(2)
    meta_col1.metric("Travellers", len(trip.travellers))
    meta_col2.metric("Currencies Used", len(used_currencies))

    st.caption(
        f"Currencies used: {', '.join(sorted(used_currencies))}"
        if used_currencies
        else "Currencies used: none yet"
    )

    render_planning_progress(trip)

    st.info(format_rate_snapshot_status(trip))

    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
    with col1:
        if st.button("Fetch exchange rate snapshot", width="stretch"):
            if used_currencies:
                try:
                    fetch_exchange_rates(
                        trip.baseCurrency,
                        used_currencies,
                        trip.exchangeRates,
                    )
                    persist_trip()
                    st.success("Exchange rates refreshed and snapshot saved.")
                except Exception as e:
                    st.warning(f"Could not fetch live rates: {str(e)}. Using default rates.")
            else:
                st.info("No currencies to fetch yet.")

    with col2:
        all_trips = load_all_trips()
        trip_exists_in_file = st.session_state.trip_name in all_trips

        def delete_current_trip():
            if trip_exists_in_file:
                deleted_name = st.session_state.trip_name
                delete_trip(deleted_name)
                all_trips = load_all_trips()
                if all_trips:
                    next_trip_name = load_last_open_trip_name() or next(iter(all_trips))
                    switch_to_trip(next_trip_name, all_trips[next_trip_name])
                else:
                    new_name, new_trip = create_new_trip()
                    switch_to_trip(new_name, new_trip)

        render_confirmed_button(
            "delete_trip",
            "Delete Trip",
            "Delete trip",
            delete_current_trip,
            disabled=not trip_exists_in_file,
        )

    with col3:
        if st.button("Duplicate Trip", width="stretch"):
            duplicated_trip = copy.deepcopy(trip)
            all_trips = load_all_trips()
            duplicated_trip.name = get_next_trip_name(
                all_trips,
                f"{trip.name} (Copy)",
            )
            save_trip(duplicated_trip, duplicated_trip.name)
            switch_to_trip(duplicated_trip.name, duplicated_trip)
            st.success(f"Duplicated trip as '{duplicated_trip.name}'")
            st.rerun()

    with col4:
        def clear_current_trip_data():
            trip.costItems.clear()
            trip.options.clear()
            trip.travellers.clear()
            trip.accommodation = None
            trip.exchangeRates.clear()

        render_confirmed_button(
            "clear_all_data",
            "Clear All Data",
            "Clear all data",
            clear_current_trip_data,
        )

    with st.expander("Manage Categories"):
        st.write("Current categories:", ", ".join(trip.categories))

        st.subheader("Quick Add Common Categories")
        cols = st.columns(4)
        for i, cat in enumerate(COMMON_CATEGORIES):
            with cols[i % 4]:
                if st.button(cat, key=f"add_common_{cat}"):
                    if cat not in trip.categories:
                        trip.categories.append(cat)
                        st.success(f"Added category: {cat}")
                        st.rerun()
                    else:
                        st.info(f"Category '{cat}' already exists")

        st.divider()
        new_category = st.text_input("Add custom category", key="new_category")
        if st.button("Add Custom Category"):
            normalized = new_category.strip()
            if normalized and normalized not in trip.categories:
                trip.categories.append(normalized)
                st.success(f"Added category: {normalized}")
            elif not normalized:
                st.warning("Enter a category name first.")
            else:
                st.info("Category already exists.")

with tabs[1]:
    st.header("Cost Items")
    show_entry_notice("cost_item")
    if st.button("Add cost item", width="stretch"):
        open_entry_dialog("cost_item")

    if st.session_state.get(ENTRY_DIALOG_KEY) == "cost_item":
        add_cost_item_dialog()

    if trip.costItems:
        st.subheader("Current Cost Items")
        for idx, cost_item in enumerate(trip.costItems):
            cost_item.costType = normalize_cost_type(cost_item.costType)
            with st.expander(cost_item_expander_label(cost_item, idx, len(trip.travellers))):
                cost_item.name = st.text_input("Name", cost_item.name, key=f"cost_name_{idx}")
                cost_item.category = st.selectbox(
                    "Category",
                    trip.categories,
                    index=(
                        trip.categories.index(cost_item.category)
                        if cost_item.category in trip.categories
                        else 0
                    ),
                    key=f"cost_cat_{idx}",
                )
                cost_item.costType = st.selectbox(
                    "Cost type",
                    cost_type_options,
                    index=cost_type_options.index(cost_item.costType),
                    format_func=cost_type_label,
                    key=f"cost_type_{idx}",
                )
                cost_item.amount = st.number_input(
                    "Amount",
                    min_value=0.0,
                    value=cost_item.amount,
                    format="%.2f",
                    key=f"cost_amt_{idx}",
                )
                cost_item.currency = st.selectbox(
                    "Currency",
                    currencies,
                    index=selected_currency_index(cost_item.currency),
                    key=f"cost_curr_{idx}",
                )
                cost_item.depositRatio = st.slider(
                    "Deposit ratio",
                    min_value=0.0,
                    max_value=1.0,
                    value=cost_item.depositRatio,
                    step=0.01,
                    key=f"cost_dep_{idx}",
                )
                st.caption(f"Deposit: {format_percent(cost_item.depositRatio)}")
                cost_item.discountRatio = st.slider(
                    "Discount ratio",
                    min_value=0.0,
                    max_value=1.0,
                    value=cost_item.discountRatio,
                    step=0.01,
                    key=f"cost_disc_{idx}",
                )
                st.caption(f"Discount: {format_percent(cost_item.discountRatio)}")
                st.markdown('<div class="delete-button-container">', unsafe_allow_html=True)

                def delete_cost_item(item_idx=idx):
                    trip.costItems.pop(item_idx)

                render_confirmed_button(
                    f"delete_cost_{idx}",
                    "Delete",
                    "Delete cost item",
                    delete_cost_item,
                )
                st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("Add your first cost item to track trip expenses.")

with tabs[2]:
    st.header("Accommodation")

    if trip.accommodation is None:
        trip.accommodation = Accommodation(0.0, trip.baseCurrency, {})

    col1, col2 = st.columns(2)
    with col1:
        trip.accommodation.totalCost = st.number_input(
            "Total accommodation cost",
            min_value=0.0,
            value=trip.accommodation.totalCost,
            format="%.2f",
            key=trip_widget_key("accom_total_cost"),
        )
    with col2:
        trip.accommodation.currency = st.selectbox(
            "Currency",
            currencies,
            index=selected_currency_index(trip.accommodation.currency, trip.baseCurrency),
            key=trip_widget_key("accom_currency"),
        )

    trip.accommodation.depositRatio = st.slider(
        "Deposit ratio",
        min_value=0.0,
        max_value=1.0,
        value=trip.accommodation.depositRatio,
        step=0.01,
        key=trip_widget_key("accom_deposit_ratio"),
    )
    st.caption(f"Deposit: {format_percent(trip.accommodation.depositRatio)}")

    show_entry_notice("room_type")
    if st.button("Add room type", width="stretch"):
        open_entry_dialog("room_type")

    if st.session_state.get(ENTRY_DIALOG_KEY) == "room_type":
        add_room_type_dialog()

    if trip.accommodation.roomTypes:
        st.subheader("Room Types")
        assignment_counts = get_room_type_assignment_counts(trip)
        for room_name, room in list(trip.accommodation.roomTypes.items()):
            assigned_count = assignment_counts.get(room_name, 0)
            capacity = room_type_capacity(room)
            room_price = trip.accommodation.room_cost(room_name)
            expander_label = room_type_display_label(trip, room_name)
            with st.expander(expander_label):
                detail_col1, detail_col2 = st.columns(2)
                detail_col1.metric("Assigned beds", f"{assigned_count}/{capacity}")
                detail_col2.metric(
                    "Price / traveller",
                    format_currency(room_price, trip.accommodation.currency),
                )
                if assigned_count > capacity:
                    st.warning(
                        f"{room_name} is over assigned. Increase capacity or move "
                        f"{assigned_count - capacity} traveller(s)."
                    )
                new_room_name = st.text_input(
                    "Room type name",
                    room.name,
                    key=f"room_name_{room_name}",
                )
                normalized_room_name = new_room_name.strip()
                if normalized_room_name and normalized_room_name != room_name:
                    if normalized_room_name in trip.accommodation.roomTypes:
                        st.warning("A room type with this name already exists.")
                    else:
                        rename_room_type(trip, room_name, normalized_room_name)
                        persist_trip()
                        st.rerun()
                elif not normalized_room_name:
                    st.warning("Room type name cannot be blank.")
                room.roomCount = st.number_input(
                    "Number of rooms",
                    min_value=1,
                    value=room.roomCount,
                    key=f"room_count_{room_name}",
                )
                room.bedsPerRoom = st.number_input(
                    "Beds per room",
                    min_value=1,
                    value=room.bedsPerRoom,
                    key=f"room_beds_{room_name}",
                )
                room.weighting = st.number_input(
                    "Weight",
                    min_value=0.1,
                    value=room.weighting,
                    format="%.2f",
                    key=f"room_weight_{room_name}",
                )
                st.markdown('<div class="delete-button-container">', unsafe_allow_html=True)

                def delete_room_type(target_room_name=room_name):
                    clear_room_type_assignments(trip, target_room_name)
                    del trip.accommodation.roomTypes[target_room_name]

                render_confirmed_button(
                    f"delete_room_{room_name}",
                    "Delete",
                    "Delete room type",
                    delete_room_type,
                )
                st.markdown('</div>', unsafe_allow_html=True)

        st.subheader("Summary")
        summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
        summary_col1.metric("Total Beds", trip.accommodation.total_beds())
        summary_col2.metric("Weighted Beds", f"{trip.accommodation.total_weighted_beds():g}")
        summary_col3.metric(
            "Base Cost / Weighted Bed",
            format_currency(
                trip.accommodation.base_cost_per_bed(),
                trip.accommodation.currency,
            ),
        )
        summary_col4.metric("Deposit", format_percent(trip.accommodation.depositRatio))
    else:
        st.info("Add room types to define accommodation allocation.")


with tabs[3]:
    st.header("Options")
    show_entry_notice("option")
    if st.button("Add option", width="stretch"):
        open_entry_dialog("option")

    if st.session_state.get(ENTRY_DIALOG_KEY) == "option":
        add_option_dialog()

    if trip.options:
        st.subheader("Current Options")
        for idx, option in enumerate(trip.options):
            with st.expander(option_expander_label(option, idx)):
                old_option_name = option.name
                new_option_name = st.text_input(
                    "Option name",
                    option.name,
                    key=f"option_name_{idx}",
                )
                normalized_option_name = new_option_name.strip()
                existing_option_names = [
                    existing_option.name
                    for existing_idx, existing_option in enumerate(trip.options)
                    if existing_idx != idx
                ]
                if normalized_option_name and normalized_option_name != old_option_name:
                    if normalized_option_name in existing_option_names:
                        st.warning("An option with this name already exists.")
                    else:
                        rename_option(trip, old_option_name, normalized_option_name)
                        option.name = normalized_option_name
                        persist_trip()
                        st.rerun()
                elif not normalized_option_name:
                    st.warning("Option name cannot be blank.")
                option.cost = st.number_input(
                    "Option cost",
                    min_value=0.0,
                    value=option.cost,
                    format="%.2f",
                    key=f"option_cost_{idx}",
                )
                option.currency = st.selectbox(
                    "Currency",
                    currencies,
                    index=selected_currency_index(option.currency),
                    key=f"option_curr_{idx}",
                )
                option.depositRatio = st.slider(
                    "Deposit ratio",
                    min_value=0.0,
                    max_value=1.0,
                    value=option.depositRatio,
                    step=0.01,
                    key=f"option_dep_{idx}",
                )
                st.caption(f"Deposit: {format_percent(option.depositRatio)}")
                st.markdown('<div class="delete-button-container">', unsafe_allow_html=True)

                def delete_option(option_idx=idx, option_name=option.name):
                    for traveller in trip.travellers:
                        traveller.selectedOptions = [
                            opt_name
                            for opt_name in traveller.selectedOptions
                            if opt_name != option_name
                        ]
                    trip.options.pop(option_idx)

                render_confirmed_button(
                    f"delete_option_{idx}",
                    "Delete",
                    "Delete option",
                    delete_option,
                )
                st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("Create equipment and baggage options here.")

with tabs[4]:
    st.header("Travellers")
    show_entry_notice("traveller")
    traveller_action_col1, traveller_action_col2 = st.columns(2)
    with traveller_action_col1:
        if st.button("Add traveller", width="stretch"):
            open_entry_dialog("traveller")
    with traveller_action_col2:
        if st.button("Bulk add travellers", width="stretch"):
            open_entry_dialog("bulk_travellers")

    if st.session_state.get(ENTRY_DIALOG_KEY) == "traveller":
        add_traveller_dialog()
    if st.session_state.get(ENTRY_DIALOG_KEY) == "bulk_travellers":
        bulk_add_travellers_dialog()

    if trip.travellers:
        traveller_labels = {
            f"{traveller.name or 'Unnamed traveller'} ({idx + 1})": idx
            for idx, traveller in enumerate(trip.travellers)
        }
        with st.expander("Bulk assignments"):
            selected_traveller_labels = st.multiselect(
                "Travellers",
                list(traveller_labels),
                key="bulk_assignment_travellers",
            )
            selected_traveller_indices = [
                traveller_labels[label] for label in selected_traveller_labels
            ]

            if trip.options:
                option_col1, option_col2 = st.columns([2, 1])
                with option_col1:
                    bulk_options = st.multiselect(
                        "Options",
                        option_names(trip),
                        key="bulk_assignment_options",
                    )
                with option_col2:
                    option_mode = st.selectbox(
                        "Mode",
                        ["Add to existing", "Replace existing"],
                        key="bulk_assignment_option_mode",
                    )
                if st.button(
                    "Apply options",
                    disabled=not selected_traveller_indices,
                    width="stretch",
                ):
                    for traveller_idx in selected_traveller_indices:
                        traveller = trip.travellers[traveller_idx]
                        if option_mode == "Replace existing":
                            traveller.selectedOptions = list(bulk_options)
                        else:
                            traveller.selectedOptions = list(
                                dict.fromkeys([*traveller.selectedOptions, *bulk_options])
                            )
                    clear_widget_state_by_prefix("traveller_options_")
                    st.rerun()

            if trip.accommodation and trip.accommodation.roomTypes:
                room_col1, room_col2 = st.columns([2, 1])
                with room_col1:
                    bulk_room_type = st.selectbox(
                        "Room type",
                        ["", *trip.accommodation.roomTypes.keys()],
                        format_func=lambda room_name: room_type_display_label(trip, room_name),
                        key="bulk_assignment_room_type",
                    )
                with room_col2:
                    st.caption("Capacity is checked before assigning.")
                if st.button(
                    "Apply room type",
                    disabled=not selected_traveller_indices,
                    width="stretch",
                ):
                    if bulk_room_type:
                        room = trip.accommodation.roomTypes[bulk_room_type]
                        capacity = room_type_capacity(room)
                        selected_set = set(selected_traveller_indices)
                        assigned_excluding_selection = sum(
                            1
                            for traveller_idx, traveller in enumerate(trip.travellers)
                            if traveller_idx not in selected_set
                            and traveller.roomType == bulk_room_type
                        )
                        if assigned_excluding_selection + len(selected_set) > capacity:
                            st.warning("That assignment would exceed the room capacity.")
                        else:
                            for traveller_idx in selected_traveller_indices:
                                trip.travellers[traveller_idx].roomType = bulk_room_type
                            clear_widget_state_by_prefix("traveller_room_")
                            st.rerun()
                    else:
                        for traveller_idx in selected_traveller_indices:
                            trip.travellers[traveller_idx].roomType = ""
                        clear_widget_state_by_prefix("traveller_room_")
                        st.rerun()

        st.subheader("Current Travellers")
        for idx, traveller in enumerate(trip.travellers):
            with st.expander(traveller_expander_label(traveller, idx, trip)):
                traveller.name = st.text_input("Name", traveller.name, key=f"traveller_name_{idx}")
                if trip.options:
                    valid_options = option_names(trip)
                    filtered_selected = [
                        opt for opt in traveller.selectedOptions if opt in valid_options
                    ]
                    traveller.selectedOptions = st.multiselect(
                        "Selected options",
                        valid_options,
                        filtered_selected,
                        key=f"traveller_options_{idx}",
                    )
                if trip.accommodation:
                    room_keys = available_room_type_options(trip, traveller.roomType)
                    current_index = (
                        room_keys.index(traveller.roomType)
                        if traveller.roomType in room_keys
                        else 0
                    )
                    traveller.roomType = st.selectbox(
                        "Room type",
                        room_keys,
                        index=current_index,
                        format_func=lambda room_name: room_type_display_label(trip, room_name),
                        key=f"traveller_room_{idx}",
                    )
                    if len(room_keys) == 1 and trip.accommodation.roomTypes:
                        st.info("All room types are fully assigned.")
                st.markdown('<div class="delete-button-container">', unsafe_allow_html=True)

                def delete_traveller(traveller_idx=idx):
                    trip.travellers.pop(traveller_idx)

                render_confirmed_button(
                    f"delete_traveller_{idx}",
                    "Delete",
                    "Delete traveller",
                    delete_traveller,
                )
                st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("Add travellers so the planner can calculate shares.")

with tabs[5]:
    st.header("Summary")

    validation_errors = validate_trip(trip)
    if validation_errors:
        for error in validation_errors:
            st.error(f"⚠️ {error}")
        st.warning("Please fix the above issues before proceeding.")

    totals = calculateTripTotals(trip, convert)
    deposit_per_person = totals["deposit"] / len(trip.travellers) if trip.travellers else 0.0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total cost", format_currency(totals["total"], trip.baseCurrency))
    c2.metric("Total deposit", format_currency(totals["deposit"], trip.baseCurrency))
    c3.metric("Total outstanding", format_currency(totals["outstanding"], trip.baseCurrency))
    c4.metric("Deposit per traveller", format_currency(deposit_per_person, trip.baseCurrency))

    with st.expander("Export", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Export Trip as JSON", width="stretch"):
                trip_data = trip.to_dict()
                trip_data["calculated_totals"] = totals
                st.download_button(
                    label="Download JSON",
                    data=json.dumps(trip_data, indent=2),
                    file_name=f"{trip.name.replace(' ', '_')}_trip.json",
                    mime="application/json",
                    width="stretch",
                )

        with col2:
            if st.button("Export Summary as CSV", disabled=not trip.travellers, width="stretch"):
                df = pd.DataFrame(build_traveller_export_rows(trip))
                csv_buffer = io.StringIO()
                df.to_csv(csv_buffer, index=False)
                st.download_button(
                    label="Download CSV",
                    data=csv_buffer.getvalue(),
                    file_name=f"{trip.name.replace(' ', '_')}_summary.csv",
                    mime="text/csv",
                    width="stretch",
                )

    st.subheader("Trip cost breakdown")
    trip_categories = calculateCategoryTotals(trip, convert)
    if trip_categories:
        category_rows = [
            {
                "Category": cat,
                "Cost": format_currency(amount, trip.baseCurrency),
                "Share": format_percent(amount / totals["total"]) if totals["total"] else "0%",
            }
            for cat, amount in trip_categories.items()
        ]
        show_dataframe(
            category_rows,
            "No cost items, accommodation, or options have been added yet.",
        )
    else:
        st.info("No cost items, accommodation, or options have been added yet.")

    if trip.travellers:
        st.subheader("Per traveller totals")
        traveller_breakdowns = [
            (traveller, calculateTravellerBreakdown(traveller, trip, convert))
            for traveller in trip.travellers
        ]
        traveller_rows = build_traveller_summary_rows(trip, traveller_breakdowns)
        show_dataframe(traveller_rows, "Add travellers to see per-person summaries.")
        for idx, (traveller, breakdown) in enumerate(traveller_breakdowns):
            name = traveller.name or f"Traveller {idx + 1}"
            details_label = (
                f"Details for {name} - "
                f"{format_currency(breakdown['total'], trip.baseCurrency)}"
            )
            with st.expander(details_label):
                detail_col1, detail_col2 = st.columns(2)
                detail_col1.metric(
                    "Traveller Total",
                    format_currency(breakdown["total"], trip.baseCurrency),
                )
                detail_col2.metric(
                    "Traveller Deposit",
                    format_currency(breakdown["deposit"], trip.baseCurrency),
                )
                category_rows = [
                    {"Category": cat, "Cost": format_currency(amount, trip.baseCurrency)}
                    for cat, amount in breakdown["categories"].items()
                ]
                show_dataframe(category_rows, "No costs assigned to this traveller yet.")
                if breakdown["selectedOptions"]:
                    st.caption(f"Selected options: {', '.join(breakdown['selectedOptions'])}")
    else:
        st.info("Add travellers to see per-person summaries.")

with tabs[6]:
    st.header("Notes")
    trip.notes = st.text_area(
        "Trip Notes",
        trip.notes,
        height=400,
        placeholder="Add any notes for this trip here...",
    )

persist_trip()
