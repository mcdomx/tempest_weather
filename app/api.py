import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.cloud import fetch_forecast, fetch_obs_history
from app.display import start_display
from app.listener import start_listener, get_state, subscribe, unsubscribe


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_listener()
    try:
        start_display()
    except Exception:
        logging.exception("LCD display failed to start; continuing without it")
    yield


app = FastAPI(title="Tempest Weather API", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/weather/latest")
async def weather_latest() -> dict:
    try:
        data = get_state("obs_st")
        if data is None:
            raise HTTPException(status_code=503, detail="No obs_st received yet")
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/weather/wind")
async def weather_wind() -> dict:
    try:
        data = get_state("rapid_wind")
        if data is None:
            raise HTTPException(status_code=503, detail="No rapid_wind received yet")
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/weather/status")
async def weather_status() -> dict:
    try:
        return {
            "hub": get_state("hub_status"),
            "device": get_state("device_status"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/weather/history")
async def weather_history(minutes: int = Query(default=60, ge=1, le=1440)) -> dict:
    try:
        observations = await fetch_obs_history(minutes)
        return {"minutes": minutes, "count": len(observations), "observations": observations}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/weather/forecast/daily")
async def weather_forecast_daily() -> dict:
    try:
        entries = await fetch_forecast("daily")
        return {"count": len(entries), "forecast": entries}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/weather/forecast/hourly")
async def weather_forecast_hourly() -> dict:
    try:
        entries = await fetch_forecast("hourly")
        return {"count": len(entries), "forecast": entries}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _sse_generator(msg_type: str) -> AsyncGenerator[str, None]:
    loop = asyncio.get_event_loop()
    queue = subscribe(msg_type, loop)
    try:
        while True:
            parsed = await queue.get()
            yield f"data: {json.dumps(parsed)}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        unsubscribe(msg_type, loop, queue)


@app.get("/weather/stream")
async def weather_stream() -> StreamingResponse:
    return StreamingResponse(_sse_generator("*"), media_type="text/event-stream")


@app.get("/weather/stream/obs")
async def weather_stream_obs() -> StreamingResponse:
    return StreamingResponse(_sse_generator("obs_st"), media_type="text/event-stream")


@app.get("/weather/stream/wind")
async def weather_stream_wind() -> StreamingResponse:
    return StreamingResponse(_sse_generator("rapid_wind"), media_type="text/event-stream")
