from fastapi import FastAPI, HTTPException, Query
from telethon.sync import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from datetime import datetime, timezone
import os

app = FastAPI()


def session_path(phone_number: str) -> str:
    return f"/data/session_{phone_number.replace('+', '').replace(' ', '')}"


@app.post("/send_code")
async def send_code(phone_number: str, api_id: int, api_hash: str):
    session = session_path(phone_number)
    client = TelegramClient(session, api_id, api_hash)

    await client.connect()
    if await client.is_user_authorized():
        await client.disconnect()
        return {"status": "already_authorized"}

    try:
        await client.send_code_request(phone_number)
        await client.disconnect()
        return {"status": "code_sent"}
    except Exception as e:
        return {"error": str(e)}


@app.post("/confirm_code")
async def confirm_code(phone_number: str, api_id: int, api_hash: str, code: str):
    session = session_path(phone_number)
    client = TelegramClient(session, api_id, api_hash)

    try:
        await client.connect()
        await client.sign_in(phone_number, code)
        await client.disconnect()
        return {"status": "authorized"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/get_messages")
async def get_messages(
    channel_name: str,
    api_id: int,
    api_hash: str,
    phone_number: str,
    from_date: str = Query(..., description="Format: DD/MM/YYYY"),
    to_date: str = Query(..., description="Format: DD/MM/YYYY")
):
    try:
        from_dt = datetime.strptime(from_date, "%d/%m/%Y").replace(tzinfo=timezone.utc)
        to_dt = datetime.strptime(to_date, "%d/%m/%Y").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Date must be in DD/MM/YYYY format")

    session = session_path(phone_number)
    client = TelegramClient(session, api_id, api_hash)

    try:
        await client.start()
        
        try:
            entity = await client.get_entity(channel_name)
        except:
            dialogs = await client.get_dialogs()
            group = next((d.entity for d in dialogs if d.name == channel_name), None)
            if not group:
                raise HTTPException(status_code=404, detail="Group not found")
            entity = group

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

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))