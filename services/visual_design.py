from typing import Any, Dict


def calculate_trip_progress(trip) -> Dict[str, Any]:
    """Calculate trip planning completion progress with detailed item information."""
    progress_items = {
        "trip_name": {
            "completed": bool(trip.name and trip.name.strip() != "New Trip"),
            "tab_index": 0,
            "tab_name": "Trip Setup",
            "field_name": "Trip Name",
            "description": "Enter a name for your trip",
        },
        "trip_description": {
            "completed": bool(trip.description and trip.description.strip()),
            "tab_index": 0,
            "tab_name": "Trip Setup",
            "field_name": "Description",
            "description": "Add a description for your trip",
        },
        "start_date": {
            "completed": bool(trip.startDate),
            "tab_index": 0,
            "tab_name": "Trip Setup",
            "field_name": "Start Date",
            "description": "Set the trip start date",
        },
        "end_date": {
            "completed": bool(trip.endDate),
            "tab_index": 0,
            "tab_name": "Trip Setup",
            "field_name": "End Date",
            "description": "Set the trip end date",
        },
        "travellers": {
            "completed": len(trip.travellers) > 0,
            "tab_index": 4,
            "tab_name": "Travellers",
            "field_name": "Travellers",
            "description": "Add at least one traveller",
        },
        "cost_items": {
            "completed": len(trip.costItems) > 0,
            "tab_index": 1,
            "tab_name": "Cost Items",
            "field_name": "Cost Items",
            "description": "Add at least one cost item",
        },
        "accommodation": {
            "completed": bool(
                trip.accommodation
                and trip.accommodation.totalCost > 0
                and trip.accommodation.roomTypes
            ),
            "tab_index": 2,
            "tab_name": "Accommodation",
            "field_name": "Accommodation",
            "description": "Add accommodation cost and at least one room type",
        },
        "options": {
            "completed": len(trip.options) > 0,
            "tab_index": 3,
            "tab_name": "Options",
            "field_name": "Options",
            "description": "Add optional extras or equipment",
        },
        "notes": {
            "completed": bool(trip.notes and trip.notes.strip()),
            "tab_index": 6,
            "tab_name": "Notes",
            "field_name": "Notes",
            "description": "Add trip notes or planning details",
        },
    }

    completed_count = sum(item["completed"] for item in progress_items.values())
    total = len(progress_items)
    percentage = (completed_count / total) * 100

    missing_items = {k: v for k, v in progress_items.items() if not v["completed"]}

    return {
        "completed": completed_count,
        "total": total,
        "percentage": percentage,
        "items": progress_items,
        "missing_items": missing_items,
    }
