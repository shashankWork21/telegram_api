from fastapi import FastAPI, HTTPException, Query
from telethon.sync import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from datetime import datetime, timezone
import os
from pydantic import BaseModel
from typing import Union, List, Optional

app = FastAPI()

# Pydantic models for request bodies
class SendCodeRequest(BaseModel):
    phone_number: str
    api_id: int
    api_hash: str

class ConfirmCodeRequest(BaseModel):
    phone_number: str
    api_id: int
    api_hash: str
    code: str
    phone_code_hash: str

class DeleteSessionRequest(BaseModel):
    phone_number: str

class GetDialogsRequest(BaseModel):
    phone_number: str
    api_id: int
    api_hash: str


def session_path(phone_number: str) -> str:
    # Create data directory if it doesn't exist
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)
    
    # Use a relative path inside the project directory
    return os.path.join(data_dir, f"session_{phone_number.replace('+', '').replace(' ', '')}")


@app.post("/send_code")
async def send_code(request: SendCodeRequest):
    session = session_path(request.phone_number)
    client = TelegramClient(session, request.api_id, request.api_hash)

    await client.connect()
    if await client.is_user_authorized():
        await client.disconnect()
        return {"status": "already_authorized"}

    try:
        result = await client.send_code_request(request.phone_number)
        await client.disconnect()
        return {"status": "code_sent", "phone_code_hash": result.phone_code_hash, "api_id": request.api_id, "api_hash": request.api_hash, "phone_number": request.phone_number}
    except Exception as e:
        return {"error": str(e)}


@app.post("/confirm_code")
async def confirm_code(request: ConfirmCodeRequest):
    session = session_path(request.phone_number)
    client = TelegramClient(session, request.api_id, request.api_hash)

    try:
        await client.connect()
        await client.sign_in(request.phone_number, request.code, phone_code_hash=request.phone_code_hash)
        await client.disconnect()
        return {"status": "authorized"}
    except Exception as e:
        return {"error": str(e)}


@app.delete("/delete_session")
async def delete_session(request: DeleteSessionRequest):
    session = session_path(request.phone_number)
    session_db = f"{session}.session"
    
    try:
        # Check if session file exists
        if os.path.exists(session_db):
            os.remove(session_db)
            return {"status": "success", "message": f"Session for {request.phone_number} deleted successfully"}
        else:
            return {"status": "not_found", "message": f"No session found for {request.phone_number}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/get_messages")
async def get_messages(
    channel_id: Union[int, str],
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

    # Try to convert channel_id to int if it's numeric
    if isinstance(channel_id, str) and channel_id.isdigit():
        channel_id = int(channel_id)

    session = session_path(phone_number)
    client = TelegramClient(session, api_id, api_hash)

    try:
        await client.start()
        
        try:
            # Get entity directly by ID
            entity = await client.get_entity(channel_id)
        except:
            raise HTTPException(status_code=404, detail="Channel not found. Use /get_dialogs to find the correct channel ID.")

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
                    if from_dt <= msg.date <= to_dt and msg.message is not None:
                        messages.append({
                            "date": msg.date.isoformat(),
                            "sender_id": msg.sender_id,
                            "message": msg.message
                        })

            if not history.messages:
                break
                
            offset_id = history.messages[-1].id

        await client.disconnect()
        return {"messages": messages}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))