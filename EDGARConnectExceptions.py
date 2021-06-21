import pytz

class SECServerClosedError(Exception):
    def __init__(self):
        utc_dt = pytz.utc.localize(dt.utcnow())
        est_timezone = pytz.timezone('US/Eastern')
        est_dt = est_timezone.normalize(utc_dt.astimezone(est_timezone))
        
        self.message = f"SEC Servers are open between 9PM and 6AM, it is currently {est_dt}"
        super().__init__(self.message)
