import psycopg

from cinema.messaging import Background


class SeatChangeListener:
    """Forward committed seat changes to SSE clients connected to this Booking instance."""

    def __init__(self, dsn, observer):
        self.dsn = dsn
        self.observer = observer
        self.connection = None

    def listen(self):
        try:
            if self.connection is None:
                self.connection = psycopg.connect(self.dsn, autocommit=True, connect_timeout=5)
                self.connection.execute("LISTEN cinema_seat_changes")
            for event in self.connection.notifies(timeout=0.5, stop_after=32):
                self.observer.changed(event.payload)
            return True
        except psycopg.Error:
            self.close()
            raise

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None

    def background(self):
        return Background("seat-changes", self.listen, self.close)
