class BaseLocales(object):
    verify_join = "Click the button below to prove you are not a robot, it will be expired in 3 minutes. If you think its too difficult, you can try use mobile app."
    invite_group = "Invite me to your group"
    expired_join = "Your join request is expired, so i rejected it."

    @classmethod
    def get(cls, key):
        return getattr(cls, key, None)


class EnLocales(BaseLocales):
    verify_join = "Click the button below to prove you are not a robot, it will be expired in 3 minutes. If you think its too difficult, you can try use mobile app."
    invite_group = "You can invite me to your group by clicking the button below, btw i need some permissions to work properly."
    expired_join = "Your join request is expired, so i rejected it."


class ZhLocales(BaseLocales):
    verify_join = "点击下方按钮证明你不是机器人，否则 3 分钟后您的加入请求会被自动拒绝。如果你认为验证太难，可以在 Telegram APP 一键验证。"
    invite_group = "你可以通过点击下方按钮邀请我加入你的群组，顺便我需要一些权限才能正常工作。"
    expired_join = "您的加入请求已经过期，所以我拒绝了它。"


def get_locales(language):
    return {
        "en": EnLocales,
        "zh": ZhLocales,
    }.get(language, EnLocales)
