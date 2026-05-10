from collections import defaultdict

from models.cost_item import CostType, normalize_cost_type


def _convert_to_base(amount, currency, trip, convert):
    return convert(amount, currency, trip.baseCurrency, trip.exchangeRates)


def _discounted_amounts(item):
    discounted = item.amount * (1 - item.discountRatio)
    deposit = discounted * item.depositRatio
    return discounted, deposit


def _options_by_name(trip):
    return {option.name: option for option in trip.options}


def _selected_options(traveller, options):
    for option_name in traveller.selectedOptions:
        option = options.get(option_name)
        if option:
            yield option


def _trip_cost_item_amounts(item, traveller_count):
    discounted, deposit = _discounted_amounts(item)
    if normalize_cost_type(item.costType) == CostType.PER_PERSON:
        return discounted * traveller_count, deposit * traveller_count
    return discounted, deposit


def format_currency(amount, currency):
    """Format a number as currency with thousands separator."""
    if isinstance(amount, (int, float)):
        return f"{amount:,.2f} {currency}"
    return f"0.00 {currency}"


def calculateTripTotals(trip, convert):
    total = 0.0
    deposit = 0.0

    for item in trip.costItems:
        item_total, item_deposit = _trip_cost_item_amounts(item, len(trip.travellers))
        total += _convert_to_base(item_total, item.currency, trip, convert)
        deposit += _convert_to_base(item_deposit, item.currency, trip, convert)

    if trip.accommodation:
        total += _convert_to_base(
            trip.accommodation.totalCost,
            trip.accommodation.currency,
            trip,
            convert,
        )
        deposit += _convert_to_base(
            trip.accommodation.totalCost * trip.accommodation.depositRatio,
            trip.accommodation.currency,
            trip,
            convert,
        )

    options = _options_by_name(trip)
    for traveller in trip.travellers:
        for option in _selected_options(traveller, options):
            total += _convert_to_base(option.cost, option.currency, trip, convert)
            deposit += _convert_to_base(
                option.cost * option.depositRatio,
                option.currency,
                trip,
                convert,
            )

    return {"total": total, "deposit": deposit, "outstanding": total - deposit}


def calculateTravellerBreakdown(traveller, trip, convert):
    categories = defaultdict(float)
    total = 0.0
    traveller_count = max(len(trip.travellers), 1)

    for item in trip.costItems:
        discounted, _ = _discounted_amounts(item)
        if normalize_cost_type(item.costType) == CostType.PER_PERSON:
            value = _convert_to_base(discounted, item.currency, trip, convert)
        else:
            value = _convert_to_base(discounted / traveller_count, item.currency, trip, convert)
        categories[item.category or "Misc"] += value
        total += value

    if trip.accommodation and traveller.roomType:
        room_type = trip.accommodation.roomTypes.get(traveller.roomType)
        if room_type:
            accommodation_cost = trip.accommodation.base_cost_per_bed() * room_type.weighting
            accommodation_value = _convert_to_base(
                accommodation_cost,
                trip.accommodation.currency,
                trip,
                convert,
            )
            categories["Accommodation"] += accommodation_value
            total += accommodation_value

    selected_options = []
    options = _options_by_name(trip)
    for option in _selected_options(traveller, options):
        option_value = _convert_to_base(option.cost, option.currency, trip, convert)
        categories["Options"] += option_value
        total += option_value
        selected_options.append(option.name)

    deposit = calculateTripTotals(trip, convert)["deposit"] / traveller_count

    return {
        "total": total,
        "deposit": deposit,
        "categories": dict(categories),
        "selectedOptions": selected_options,
        "roomType": traveller.roomType,
    }


def calculateCategoryTotals(trip, convert):
    categories = defaultdict(float)

    for item in trip.costItems:
        item_total, _ = _trip_cost_item_amounts(item, len(trip.travellers))
        value = _convert_to_base(item_total, item.currency, trip, convert)
        categories[item.category or "Misc"] += value

    if trip.accommodation:
        categories["Accommodation"] += _convert_to_base(
            trip.accommodation.totalCost,
            trip.accommodation.currency,
            trip,
            convert,
        )

    options = _options_by_name(trip)
    for traveller in trip.travellers:
        for option in _selected_options(traveller, options):
            categories["Options"] += _convert_to_base(
                option.cost,
                option.currency,
                trip,
                convert,
            )

    return dict(categories)
