from hermes_state import SessionDB


def test_telegram_chat_stop_state_persists_and_is_profile_scoped(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        assert db.is_telegram_chat_paused(chat_id="u1", profile_name="main") is False

        db.set_telegram_chat_paused(chat_id="u1", user_id="u1", profile_name="main", paused=True)

        assert db.is_telegram_chat_paused(chat_id="u1", profile_name="main") is True
        assert db.is_telegram_chat_paused(chat_id="u1", profile_name="other") is False
        db.set_telegram_chat_paused(chat_id="u1", user_id="u1", profile_name="main", paused=False)
        assert db.is_telegram_chat_paused(chat_id="u1", profile_name="main") is False
    finally:
        db.close()
