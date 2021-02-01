
SEP = '|'


class ModelData(str):
    def __new__(cls, model: str, path: str, phrases: str or None):
        # noinspection PyArgumentList
        obj = str.__new__(cls, path)
        obj.model, obj.path = model, path
        obj.phrase, obj.opt_phrase, obj.sensitivity = (), (), None
        obj._init_phrase(phrases)
        return obj

    def info(self) -> str:
        count = len(self.phrase)
        phrase = 'YES[{}]'.format(count) if count > 1 else 'YES' if count else 'NO'
        return 'M: {}; S: {}; PH: {}; PA: {}'.format(repr(self.model), self.sensitivity or 'DEF', phrase, repr(self.path))

    def _init_phrase(self, phrase: str):
        if not phrase:
            return
        phrase = self._init_sensitivity(phrase)
        data = [x for x in (x.strip() for x in phrase.split(SEP)) if x]
        if data:
            self.phrase = data
            self.opt_phrase = [prepared_text(x) for x in data]

    def _init_sensitivity(self, phrase: str) -> str:
        try:
            candidate, new_phrase = phrase.split(';', 1)
        except ValueError:
            return phrase

        sensitivity = None
        if candidate:
            if candidate.isdigit():
                try:
                    sensitivity = int(candidate)
                except ValueError:
                    pass
            if sensitivity is None:
                try:
                    sensitivity = round(float(candidate), 2)
                except ValueError:
                    pass
        if sensitivity is not None and 0 <= sensitivity <= 1:
            self.sensitivity = sensitivity
            return new_phrase.lstrip(' ')
        return phrase


class ModelsStorage(list):
    STRIP = ',.!? '
    _EMPTY = '<NOPE>'

    def __init__(self, paths=(), models=(), phrases=None, no_models=False):
        super().__init__()
        self.no_models = no_models
        if self.no_models:
            self.append(ModelData(self._EMPTY, self._EMPTY, None))
        else:
            phrases = phrases or {}
            for model, path, in zip(models, paths):
                self.append(ModelData(model, path, phrases.get(model)))

    def model_info_by_id(self, model: int):
        if self.no_models:
            return (self._EMPTY,) * 3
        model -= 1
        if len(self) > model > -1:
            model_name = self[model].model
            phrase = SEP.join(self[model].phrase)
            msg = phrase and ': "{}"'.format(phrase)
        else:
            model_name, phrase = str(model), ''
            msg = ': "model id out of range: {} > {}"'.format(model, len(self) - 1)
        return model_name, phrase, msg

    def sensitivities(self, default_sensitivity: float) -> tuple:
        return tuple([x.sensitivity or default_sensitivity for x in self])

    def msg_parse(self, text: str, phrases: str) -> tuple:
        if self.no_models:
            return self._EMPTY, text
        text2 = prepared_text(text)
        for phrase in phrases.split(SEP):
            offset = text2.find(prepared_text(phrase))
            if offset > -1:
                return phrase, text[offset + len(phrase):].lstrip(self.STRIP)
        return None, None

    def text_processing(self, text, candidate=None):
        if not (text and isinstance(text, str)) or self.no_models:
            return None
        text2 = prepared_text(text)
        if candidate:
            model, phrase, _ = candidate
            offset = text2.find(prepared_text(phrase))
            if offset > -1:
                result = text[offset + len(phrase):].lstrip(self.STRIP)
                if result:
                    return model, phrase, result

        for item in self:
            for id_, phrase in enumerate(item.opt_phrase):
                offset = text2.find(phrase)
                if offset > -1:
                    phrase = item.phrase[id_]
                    return item.model, phrase, text[offset + len(phrase):].lstrip(self.STRIP)
        return None


def prepared_text(text: str) -> str:
    return ' ' + ''.join(' ' if x in ',.!?' else x for x in text.lower().replace('ё', 'е')) + ' '
