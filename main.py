from fastapi import FastAPI, HTTPException, Query
from telethon.sync import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from datetime import datetime, timezone
import os
import asyncio
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
    client = None
    
    try:
        client = TelegramClient(session, request.api_id, request.api_hash)
        await client.connect()
        
        if await client.is_user_authorized():
            return {"status": "already_authorized"}

        result = await client.send_code_request(request.phone_number)
        return {"status": "code_sent", "phone_code_hash": result.phone_code_hash}
    
    except Exception as e:
        return {"error": str(e)}
    
    finally:
        if client and client.is_connected():
            await client.disconnect()


@app.post("/confirm_code")
async def confirm_code(request: ConfirmCodeRequest):
    session = session_path(request.phone_number)
    client = None
    
    try:
        client = TelegramClient(session, request.api_id, request.api_hash)
        await client.connect()
        
        await client.sign_in(request.phone_number, request.code, phone_code_hash=request.phone_code_hash)
        return {"status": "authorized"}
    
    except Exception as e:
        return {"error": str(e)}
    
    finally:
        if client and client.is_connected():
            await client.disconnect()


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


@app.post("/get_dialogs")
async def get_dialogs(request: GetDialogsRequest):
    """Get all dialogs (chats/channels) with their IDs."""
    session = session_path(request.phone_number)
    client = None
    
    try:
        client = TelegramClient(session, request.api_id, request.api_hash)
        await client.connect()
        
        if not await client.is_user_authorized():
            return {"error": "User not authorized. Please authorize first."}
        
        dialogs = await client.get_dialogs()
        dialog_list = []
        
        for dialog in dialogs:
            entity = dialog.entity
            dialog_info = {
                "id": entity.id,
                "name": dialog.name,
                "type": "channel" if hasattr(entity, "broadcast") and entity.broadcast else "group" if hasattr(entity, "megagroup") and entity.megagroup else "chat",
                "username": entity.username if hasattr(entity, "username") and entity.username else None
            }
            dialog_list.append(dialog_info)
            
        return {"dialogs": dialog_list}
    
    except Exception as e:
        return {"error": str(e)}
    
    finally:
        if client and client.is_connected():
            await client.disconnect()


@app.get("/get_messages")
async def get_messages(
    channel_id: Union[int, str],
    api_id: int,
    api_hash: str,
    phone_number: str,
    from_date: str = Query(..., description="Format: DD/MM/YYYY"),
    to_date: str = Query(..., description="Format: DD/MM/YYYY"),
    limit: int = Query(100, description="Limit of messages per batch")
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
    client = None
    
    try:
        client = TelegramClient(session, api_id, api_hash)
        await client.connect()
        
        if not await client.is_user_authorized():
            raise HTTPException(status_code=401, detail="User not authorized. Please authorize first.")
        
        try:
            # Get entity directly by ID
            entity = await client.get_entity(channel_id)
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"Channel not found: {str(e)}. Use /get_dialogs to find the correct channel ID.")

        offset_id = 0
        messages = []
        
        # Set a reasonable max messages limit to prevent overwhelming the API
        max_messages = 1000
        total_retrieved = 0

        while total_retrieved < max_messages:
            try:
                history = await client(GetHistoryRequest(
                    peer=entity,
                    offset_id=offset_id,
                    offset_date=None,
                    add_offset=0,
                    limit=min(limit, 100),  # Telegram API limit is 100
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
                
                offset_id = history.messages[-1].id
                total_retrieved += len(history.messages)
                
                # Small delay to avoid rate limits
                await asyncio.sleep(0.5)
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error retrieving messages: {str(e)}")

        return {"messages": messages, "count": len(messages)}
    
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        if client and client.is_connected():
            await client.disconnect()