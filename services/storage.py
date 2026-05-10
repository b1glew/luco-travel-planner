import json
import os
import tempfile

from models.trip import Trip

TRIPS_FILE = "trips.json"
METADATA_KEY = "__metadata__"
LAST_OPEN_TRIP_KEY = "last_open_trip"


def _read_collection(filename):
    if not os.path.exists(filename):
        return {}

    with open(filename, encoding="utf-8") as f:
        data = json.load(f)
        return data if isinstance(data, dict) else {}


def _load_collection(filename=TRIPS_FILE):
    try:
        data = _read_collection(filename)
    except json.JSONDecodeError:
        return {}, {}

    metadata = data.get(METADATA_KEY, {})
    if not isinstance(metadata, dict):
        metadata = {}

    trips = {}
    for name, trip_data in data.items():
        if name == METADATA_KEY or not isinstance(trip_data, dict):
            continue
        try:
            trips[name] = Trip.from_dict(trip_data)
        except KeyError:
            continue

    return trips, metadata


def _save_collection(trips, metadata, filename=TRIPS_FILE):
    data = {METADATA_KEY: metadata}
    data.update({name: trip.to_dict() for name, trip in trips.items()})

    directory = os.path.dirname(os.path.abspath(filename)) or "."
    with tempfile.NamedTemporaryFile(
        "w",
        dir=directory,
        delete=False,
        encoding="utf-8",
    ) as f:
        json.dump(data, f, indent=2)
        f.write("\n")
        temp_filename = f.name

    os.replace(temp_filename, filename)


def load_all_trips(filename=TRIPS_FILE):
    """Load all trips from the collection file. Returns dict of trip_name -> Trip."""
    trips, _ = _load_collection(filename)
    return trips


def load_last_open_trip_name(filename=TRIPS_FILE):
    """Return the name of the last opened trip if it still exists."""
    trips, metadata = _load_collection(filename)
    trip_name = metadata.get(LAST_OPEN_TRIP_KEY)
    return trip_name if trip_name in trips else None


def set_last_open_trip(trip_name, filename=TRIPS_FILE):
    """Persist which trip should be opened on the next app load."""
    trips, metadata = _load_collection(filename)
    if trip_name not in trips:
        return False

    metadata[LAST_OPEN_TRIP_KEY] = trip_name
    _save_collection(trips, metadata, filename)
    return True


def save_trip(trip, trip_name, filename=TRIPS_FILE, mark_open=True):
    """Save a single trip to the collection file."""
    trips, metadata = _load_collection(filename)
    trips[trip_name] = trip
    if mark_open:
        metadata[LAST_OPEN_TRIP_KEY] = trip_name

    _save_collection(trips, metadata, filename)


def delete_trip(trip_name, filename=TRIPS_FILE):
    """Delete a trip from the collection file."""
    trips, metadata = _load_collection(filename)
    if trip_name in trips:
        del trips[trip_name]
        if metadata.get(LAST_OPEN_TRIP_KEY) == trip_name:
            metadata[LAST_OPEN_TRIP_KEY] = next(iter(trips), None)
        _save_collection(trips, metadata, filename)
        return True
    return False


def trip_exists(trip_name, filename=TRIPS_FILE):
    """Check if a trip exists."""
    trips = load_all_trips(filename)
    return trip_name in trips
