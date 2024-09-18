# /endpoint/verify 的服务器
# 用于验证用户的登录状态

import time
from enum import Enum

import telebot.util
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel, SecretStr, ConfigDict
from starlette.responses import JSONResponse

from const import EXPIRE_M_TIME
from core.death_queue import JOIN_MANAGER, JoinRequest
from core.mongo import MONGO_ENGINE
from core.mongo_odm import VerifyRequest
from server.validate_cloudflare import validate_cloudflare_turnstile
from setting.cloudflare import CloudflareSetting
from setting.server import ServerSetting
from setting.telegrambot import BotSetting, BOT
from utils.signature import generate_sign, generate_oko

app = FastAPI()
if ServerSetting.cors_origin:
    origins = ServerSetting.cors_origin.split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
TELEGRAM_BOT_TOKEN = BotSetting.token


class Source(BaseModel):
    chat_id: str
    message_id: str
    timestamp: str
    signature: str


class VerifyData(BaseModel):
    """
    响应数据
    """
    id: str
    source: Source
    acc: dict
    signature: str
    web_app_data: str
    timestamp: str

    model_config = ConfigDict(extra="allow")


class CloudflareData(BaseModel):
    """
    Cloudflare 验证数据
    """
    source: Source
    turnstile_token: str
    web_app_data: str


class EnumStatu(Enum):
    success = "success"
    error = "error"


@app.get("/endpoints")
async def read_endpoints():
    # RockRoll The World
    return {"message": "open this page in IE6"}


@app.post("/endpoints/verify-cloudflare")
async def verify_cloudflare(data: CloudflareData):
    web_app_data = telebot.util.parse_web_app_data(token=TELEGRAM_BOT_TOKEN, raw_init_data=data.web_app_data)
    if not web_app_data:
        logger.warning(f"Unsigned Request Received From {data.source}")
        return JSONResponse(
            status_code=400,
            content={"status": EnumStatu.error.value, "message": "BAD_REQUEST"}
        )
    try:
        validated = validate_cloudflare_turnstile(
            turnstile_response=data.turnstile_token,
            cloudflare_secret_key=SecretStr(CloudflareSetting.cloudflare_secret_key)
        )
    except Exception as exc:
        logger.exception(f"Failed to validate cloudflare: {exc}")
        return JSONResponse(
            status_code=400,
            content={"status": EnumStatu.error.value, "message": "SERVER_ERROR"}
        )
    else:
        if not validated.success:
            logger.info(f"Cloudflare Verify Failed {data.source} - {validated.error_codes}")
            return JSONResponse(
                status_code=400,
                content={"status": EnumStatu.error.value, "message": "CAPTCHA_FAILED"}
            )
        else:
            logger.info(f"Cloudflare Verify Success {data.source}")
    return JSONResponse(
        status_code=200,
        content={"status": EnumStatu.success.value}
    )


@app.post("/endpoints/verify-captcha")
async def verify_captcha(captcha_data: VerifyData):
    # 获取可信数据
    web_app_data = telebot.util.parse_web_app_data(token=TELEGRAM_BOT_TOKEN, raw_init_data=captcha_data.web_app_data)

    if not web_app_data:
        logger.warning(f"Unsigned Request Received From {captcha_data.source}")
        return JSONResponse(
            status_code=400,
            content={"status": EnumStatu.error.value, "message": "BAD_REQUEST"}
        )
    try:
        # 用户ID
        user_id = web_app_data['user']['id']
        # 验证的群组ID
        chat_id = captcha_data.source.chat_id
        # 机器人发送出去的消息ID
        message_id = captcha_data.source.message_id
        # 用户加入群组时间（我们机器人的签名时间）
        join_time = captcha_data.source.timestamp
        # 现在的时间...
        now_m_time = time.time() * 1000
    except KeyError:
        return JSONResponse(
            status_code=400,
            content={"status": EnumStatu.error.value, "message": "UNCOMPLETED_REQUEST"}
        )
    recover_sign = generate_sign(
        chat_id=chat_id,
        message_id=message_id,
        user_id=user_id,
        join_time=join_time,
        secret_key=SecretStr(BotSetting.token)
    )
    if recover_sign != captcha_data.signature:
        logger.error(f"Someone Try To Fake Request {captcha_data.source}")
        return JSONResponse(
            status_code=400,
            content={"status": EnumStatu.error.value, "message": "FAKE_REQUEST"}
        )
    logger.info(f"[USER] {user_id}")
    logger.info(f"[OKO] {generate_oko(data=captcha_data.web_app_data, time=captcha_data.timestamp)} {captcha_data.id}")
    # 会话过旧，虽然我们有死亡队列，但是这里还是要做一下判断，防止重放攻击
    if now_m_time - int(join_time) > EXPIRE_M_TIME:
        return JSONResponse(
            status_code=400,
            content={"status": EnumStatu.error.value, "message": "EXPIRED_REQUEST"}
        )
    logger.info(f"[Source] {captcha_data.source}")
    logger.info(f"[User] {captcha_data.acc}")
    logger.info(f"[Telegram] {web_app_data}")
    if not captcha_data.acc.get("verify_mode"):
        return JSONResponse(
            status_code=400,
            content={"status": EnumStatu.error.value, "message": "CAPTCHA_FAILED"}
        )
    # Success Accept User's Join Request
    # 删除死亡队列
    try:
        data = await JOIN_MANAGER.read()
        removed = []
        for join_request in data.join_queue:
            join_request: JoinRequest
            if str(join_request.user_id) == str(user_id) and str(join_request.chat_id) == str(chat_id):
                removed.append(join_request)
        if not removed:
            logger.error(f"JOIN_MANAGER Not Found[{user_id}-{chat_id}]")
        else:
            for join_request in removed:
                data.join_queue.remove(join_request)
            await JOIN_MANAGER.save(data)
    except Exception as exc:
        logger.error(f"JOIN_MANAGER Failed {exc}")
    # 更新记录
    try:
        history = await MONGO_ENGINE.find_one(VerifyRequest, VerifyRequest.signature == captcha_data.signature)
        if not history:
            logger.error(f"MONGO_ENGINE History Not Found {captcha_data.source}")
        history.passed = True
        await MONGO_ENGINE.save(history)
    except Exception as exc:
        logger.error(f"Modify Request Failed when {exc}")
    try:
        await BOT.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
        await BOT.delete_message(chat_id=user_id, message_id=message_id)
    except Exception as exc:
        logger.exception(f"Approve Request Failed {exc}")
    finally:
        # Accept user's join request
        return JSONResponse(
            status_code=202,
            content={"status": EnumStatu.success.value}
        )
