from Cheetah.Filters import WebSafe,EncodeUnicode,RawOrEncodedUnicode

class webSafeFilter(WebSafe):
    def filter(self, val, **kw):
        if val is None: return ''
        return WebSafe.filter(self,val,**kw)
