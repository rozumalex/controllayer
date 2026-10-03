from app.tasks.ping import ping


def test_ping() -> None:
    # given
    task = ping

    # when / then
    assert task.apply().get() == "pong"
