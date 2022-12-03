from types import FunctionType
from typing import Dict
from influxdb import DataFrameClient
import fitbit
import json
import datetime
import os
import pandas as pd
import time
import logging
import oauth

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s {%(pathname)s:%(lineno)d} %(levelname)s - %(message)s")

OATH_TOKEN_PATH = os.environ.get("OATH_FILE_LOCATION", "fitbit_oauth.json")
CACHE_DIR = "./.cache/"

# Get the oldest date. Options are hard coded here, or env['DATE_OF_PURCHSE'] in iso format.
OLDEST_DATE = os.environ.get("DATE_OF_PURCHSE", "2022-01-01T00:00:00")
OLDEST_DATE = datetime.datetime.fromisoformat(OLDEST_DATE)


def dump_token(data, token):
    logging.info(f"Writing token {token} to file {OATH_TOKEN_PATH}")
    token["secret"] = data["secret"]
    token["client_id"] = data["client_id"]
    json.dump(token, open(OATH_TOKEN_PATH, "w", encoding="utf-8"))


def get_refresh_cb(data: dict) -> FunctionType:
    def refresh_cb(token: dict):
        logging.warning(f"Refreshing my oauth token - {token}")
        dump_token(data, token)

    return refresh_cb


def browser_auth(data: dict) -> fitbit.Fitbit:
    newclient = oauth.OAuth2Server(data["client_id"], data["secret"])
    newclient.browser_authorize()
    token = newclient.fitbit.client.session.token
    dump_token(data, token)
    newclient.fitbit.get_bodyweight()
    return newclient.fitbit


def get_fitbit_client() -> fitbit.Fitbit:
    data = json.load(open(OATH_TOKEN_PATH, encoding="utf-8"))
    try:
        client = fitbit.Fitbit(
            data["client_id"],
            data["secret"],
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=data["expires_at"],
            refresh_cb=get_refresh_cb(data),
        )
    except Exception:
        logging.error(f"Failed to connect to fitbit. Probably need a new token.\n{data} ")
        client = browser_auth(data)
    return client


def adv(ll: float) -> float:
    """The purpose of this function is left for the
    reader to discover
    """
    avg = sum(ll) / len(ll)
    return avg


def merge_sleeps(a: dict, b: dict) -> dict:
    return {
        "awakeCount": sum([a["awakeCount"], b["awakeCount"]]),  # 1,
        "awakeDuration": sum([a["awakeDuration"], b["awakeDuration"]]),  # 1,
        "awakeningsCount": sum([a["awakeningsCount"], b["awakeningsCount"]]),  # 55,
        "dateOfSleep": max([a["dateOfSleep"], b["dateOfSleep"]]),  # '2022-01-01',
        "duration": sum([a["duration"], b["duration"]]),  # 23760000,
        "efficiency": adv([a["efficiency"], b["efficiency"]]),  # 80,
        "endTime": max([a["endTime"], b["endTime"]]),  # '2022-01-01T07:00:00.000',
        "minutesAfterWakeup": sum([a["minutesAfterWakeup"], b["minutesAfterWakeup"]]),  # 1,
        "minutesAsleep": sum([a["minutesAsleep"], b["minutesAsleep"]]),  # 333,
        "minutesAwake": sum([a["minutesAwake"], b["minutesAwake"]]),  # 333,
        "restlessCount": sum([a["restlessCount"], b["restlessCount"]]),  # 33,
        "startTime": min([a["startTime"], b["startTime"]]),  # '2022-01-01T01:00:00.000',
        "timeInBed": sum([a["timeInBed"], b["timeInBed"]]),
    }


def write_to_influxdb(client, df, name, dbname):
    client.write_points(df, database=dbname, measurement=name, batch_size=20)
    time.sleep(10)  # Be nice to the API and it'll be nice to you


def collect_activity(fitbit_client: fitbit.Fitbit, activity: str) -> Dict:
    """collect fitbit activity.
    Activity data is cached in ./.cache/ - so this function can be run many times
    per day without hitting the fitbit api threshold.
    returns whatever fitbit.Fitbit.time_series collects. Cached. from OLDEST_DATE > today
    Args:
        fitbit_client (fitbit.Fitbit): fitbit client
        activity (str): string. view the fitbit docs

    Raises:
        Exception: more than 1000 days of data.

    Returns:
        Dict: whatever fitbit.Fitbit.time_series collects. Cached. from OLDEST_DATE > today
    """
    today = datetime.datetime.now().isoformat()[:10]
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(CACHE_DIR, activity.replace("/", "_") + today + ".json")
    daily = []
    if not os.path.exists(cache_file):
        key = activity.replace("/", "-")
        for from_date, to_date in date_generator_99_days():
            daily += fitbit_client.time_series(activity, base_date=from_date, end_date=to_date)[key]
        open(cache_file, "w").write(json.dumps(daily))
    else:
        logging.info("Using cache!")
        daily = json.loads(open(cache_file).read())
    return daily


def date_generator_99_days():
    """generate date ranges in chunks of 99 days from OLDEST_DATE to today

    :yield: (date1, date2)
    """
    from_date = OLDEST_DATE
    to_date = datetime.datetime.today()
    while from_date <= to_date:
        yield from_date, from_date + datetime.timedelta(days=99)
        from_date = from_date + datetime.timedelta(days=99)


def nap_filter(sleeps: dict) -> dict:
    """Sleep data is messy, Going to filter out naps and
        Filter to the largest sleep for each day
    Args:
        sleeps (dict): data from fitbit

    Returns:
        dict: filtered data.
    """
    raw_data_dict = {}
    for d in sleeps:
        # Debugging, makes viewing the data better
        del d["minuteData"]

        # First, filter out naps
        start_hour = int(d["startTime"][11:13])
        end_hour = int(d["endTime"][11:13])
        if 9 < start_hour < 18:
            if 11 < end_hour < 20:
                continue
        newdate = datetime.datetime.fromisoformat(d["dateOfSleep"])

        # Two sleeps on the same day, usually rare - maybe i got up in the night for a snack? Just merge the sleeps
        if newdate in raw_data_dict:
            raw_data_dict[newdate] = merge_sleeps(d, raw_data_dict[newdate])

        else:
            raw_data_dict[newdate] = d
    return list(raw_data_dict.values())


def main():
    fitbit_client = get_fitbit_client()
    password = os.environ.get("INFLUXDBPASSWORD", "admin")
    username = os.environ.get("INFLUXDBUSERNAME", "admin")
    ip = os.environ.get("INFLUXDBIP", "127.0.0.1")
    port = os.environ.get("INFLUXDBPORT", "8086")
    dbname = os.environ.get("INFLUXDB_DB", "fitbit")
    if password == username == "admin":
        logging.warning("using default admin username/password. Probably dont have the env set properly")
    db = DataFrameClient(
        host=ip,
        port=int(port),
        username=username,
        password=password,
        ssl=False,
        verify_ssl=False,
    )

    # Drop and recreate the DB. TODO incrementally update?
    db.drop_database(dbname)
    db.create_database(dbname)
    # One shard per year.
    db.alter_retention_policy("autogen", dbname, "INF", 1, shard_duration="52w")

    # Heart rate
    raw_data = collect_activity(fitbit_client, "activities/heart")
    first_day = datetime.datetime.fromisoformat(raw_data[0]["dateTime"])
    daterange = pd.date_range(start=first_day, periods=len(raw_data), freq="D")
    data = [x["value"].get("restingHeartRate", None) for x in raw_data]
    df = pd.DataFrame(data=data, index=daterange)
    write_to_influxdb(db, df, "resting_hr", dbname)

    # Minutes in Peak|Fat Burn|Cardio
    raw_data = collect_activity(fitbit_client, "activities/heart")
    first_day = datetime.datetime.fromisoformat(raw_data[0]["dateTime"])
    daterange = pd.date_range(start=first_day, periods=len(raw_data), freq="D")
    all_zones = [x["value"]["heartRateZones"] for x in raw_data]
    filtered_zones = [filter(lambda x: x["name"] in ("Peak", "Fat Burn", "Cardio"), x) for x in all_zones]
    sum_days = [sum(map(lambda x: x["minutes"], x)) for x in filtered_zones]
    df = pd.DataFrame(data=sum_days, index=daterange)
    write_to_influxdb(db, df, "mins_exercise", dbname)

    # Sleep!
    raw_data_unfiltered = collect_activity(fitbit_client, "sleep")
    raw_data = nap_filter(raw_data_unfiltered)

    # Date range should be from day of purchase to today
    first_day = datetime.datetime.fromisoformat(raw_data[-1]["dateOfSleep"])  # REVERSE ORDER WTF FITBIT
    daterange = pd.date_range(start=first_day, periods=len(raw_data), freq="D")

    # Start writing data
    # Write ones that dont require manipulating types
    for sleep_type in ["awakeCount", "awakeningsCount", "efficiency", "minutesAsleep"]:
        data = [x[sleep_type] for x in raw_data]
        df = pd.DataFrame(data=data, index=daterange)
        write_to_influxdb(db, df, f"sleep_{sleep_type}", dbname)

    # Turn sleep times (full date iso) to millisecond of the day. Nicer for grafana
    sleep_times = [":".join(x["startTime"].split("T"))[11:-4] for x in raw_data]
    sleep_times = [int(x[0:2]) * 60 * 60 + int(x[3:5]) * 60 + int(x[6:8]) for x in sleep_times]
    wake_times = [":".join(x["endTime"].split("T"))[11:-4] for x in raw_data]
    wake_times = [int(x[0:2]) * 60 * 60 + int(x[3:5]) * 60 + int(x[6:8]) for x in wake_times]
    df = pd.DataFrame(data=wake_times, index=daterange)
    write_to_influxdb(db, df, "sleep_sleeptime", dbname)
    df = pd.DataFrame(data=sleep_times, index=daterange)
    write_to_influxdb(db, df, "sleep_waketime", dbname)


if __name__ == "__main__":
    main()
