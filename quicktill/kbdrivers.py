import hashlib
from . import user


class nullfilter:
    """Keyboard input filter that passes on all events unchanged"""
    def __call__(self, keys):
        return keys


class _magstripecode:
    """A keycode used to indicate the start or end of a magstripe card
    track.
    """
    def __init__(self, code):
        self.magstripe = code

    def __str__(self):
        return f"Magstripe {self.magstripe}"


class prehkeyboard:
    """Keyboard input filter for Preh keyboards

    Converts sequences of the form [xyz] to other keycodes.

    Optionally converts magnetic stripe card input of the form
    [M1H]track1[M1T][M2H]track2[M2T][M3H]track3[M3T] to user tokens.
    """
    def __init__(self, kb, magstripe=[
            ("M1H", "M1T"),
            ("M2H", "M2T"),
            ("M3H", "M3T"),
    ]):
        self.inputs = {}
        # Compatibility: if keys are strings, values are keycodes
        if isinstance(kb, list):
            for loc, code in kb:
                self.inputs[loc.upper()] = code
        else:
            maxrow = max(row for row, col in kb.keys())
            rows = list(reversed("ABCDEFGHIJKLMNOPQRSTUVWXYZ"[:maxrow + 1]))
            for loc, key in kb.items():
                row, col = loc
                for x in range(0, key.width):
                    for y in range(0, key.height):
                        self.inputs[f"{rows[row + y]}{col + x + 1:02}"] = \
                            key.keycode
        self.ibuf = []  # Sequence of characters received after a '['
        self.decode = False  # Are we reading into ibuf at the moment?
        if magstripe:
            for start, end in magstripe:
                self.inputs[start] = _magstripecode(start)
                self.inputs[end] = _magstripecode(end)
            self.finishmagstripe = end
        self.magstripe = None  # Magstripe read in progress if not-None

    def _pass_on_buffer(self):
        # A sequence that started '[...' didn't finish with ']' so we
        # pass it on unchanged
        self._handle_decoded_input('[')
        for i in self.ibuf:
            self._handle_decoded_input(i)
        self.decode = False
        self.ibuf = []

    def _handle_input(self, k):
        # First layer of decoding: spot and replace tokens that look
        # like [...]
        if self.decode:
            if k == ']':
                s = ''.join(self.ibuf)
                if s.upper() in self.inputs:
                    self.decode = False
                    self.ibuf = []
                    self._handle_decoded_input(self.inputs[s.upper()])
                else:
                    self._pass_on_buffer()
                    self._handle_decoded_input(']')
            elif isinstance(k, str):
                self.ibuf.append(k)
            else:
                self._pass_on_buffer()
                self._handle_decoded_input(k)
            if len(self.ibuf) > 3:
                self._pass_on_buffer()
        elif k == '[':
            self.decode = True
        else:
            self._handle_decoded_input(k)

    def _handle_decoded_input(self, k):
        # Second layer of decoding: spot sequences of magstripe tokens
        # and save/hash all the keypresses between them into a user
        # token
        if hasattr(k, 'magstripe'):
            # It was one of the magstripe codes.
            if self.magstripe is None:
                self.magstripe = []
            if k.magstripe == self.finishmagstripe:
                mr = ''.join(self.magstripe)
                self.magstripe = None
                if "BadRead" in mr:
                    return
                k = user.token(
                    "magstripe:" + hashlib.sha1(
                        mr.encode('utf-8')).hexdigest()[:16])
        if self.magstripe is not None and isinstance(k, str):
            self.magstripe.append(k)
        else:
            self._obuf.append(k)

    def __call__(self, keys):
        # We should never be called recursively so we can accumulate
        # output tokens in a list while mutating our internal state.
        self._obuf = []
        for k in keys:
            self._handle_input(k)
        return self._obuf
