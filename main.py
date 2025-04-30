from fastapi import FastAPI, Query
from telethon.sync import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from datetime import datetime
import asyncio

app = FastAPI()

@app.get("/get_messages")
async def get_messages(
    channel_name: str,
    api_id: int,
    api_hash: str,
    phone_number: str,
    from_date: str = Query(..., description="Format: DD/MM/YYYY"),
    to_date: str = Query(..., description="Format: DD/MM/YYYY")
):
    session_name = f"session_{phone_number.replace('+', '').replace(' ', '')}"

    # ⬇️ Update to parse DD/MM/YYYY format
    from_dt = datetime.strptime(from_date, "%d/%m/%Y")
    to_dt = datetime.strptime(to_date, "%d/%m/%Y")

    client = TelegramClient(session_name, api_id, api_hash)

    await client.start(phone=phone_number)
    entity = await client.get_entity(channel_name)

    offset_id = 0
    limit = 100
    messages = []

    while True:
        history = await client(GetHistoryRequest(
            peer=entity,
            offset_id=offset_id,
            offset_date=None,
            add_offset=0,
            limit=limit,
            max_id=0,
            min_id=0,
            hash=0
        ))

        if not history.messages:
            break

        for msg in history.messages:
            if hasattr(msg, 'date') and hasattr(msg, 'message'):
                if from_dt <= msg.date <= to_dt:
                    messages.append({
                        "date": msg.date.isoformat(),
                        "sender_id": msg.sender_id,
                        "message": msg.message
                    })

        offset_id = history.messages[-1].id

    await client.disconnect()
    return {"messages": messages}