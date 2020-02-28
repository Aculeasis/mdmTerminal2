import hashlib


def check_token_with_totp(token: str, hash_: str, time_, interval=2, drift=2):
    def check(salt: int) -> bool:
        return hashlib.sha512((token + str(salt)).encode()).hexdigest() == hash_
    return check(_salt(interval, time_)) or _salt(interval, time_ - drift) or _salt(interval, time_ + drift)


def _salt(interval: int, time_) -> int:
    return int(round(time_) / interval)
