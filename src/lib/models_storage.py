

class ModelsStorage(list):
    STRIP = ',.!? '
    SEP = '|'
    _EMPTY = '<NOPE>'

    def __init__(self, seq=(), phrases=None, models=(), no_models=False):
        super().__init__(seq)
        self._phrases, self._opt_phrases, self._models = {}, {}, models
        self.no_models = no_models
        if self.no_models:
            self.clear()
            self._models = (self._EMPTY,)
            self.append(self._EMPTY)
        else:
            self._init_phrases(phrases or {})
        assert len(self) == len(self._models)

    def _init_phrases(self, phrases: dict):
        for model in self._models:
            data = [x for x in (x.strip() for x in phrases.get(model, '').split(self.SEP)) if x]
            if data:
                self._phrases[model] = data
                self._opt_phrases[model] = [self._prep_text(x) for x in data]

    def model_info_by_id(self, model: int):
        if self.no_models:
            return (self._EMPTY,) * 3
        model -= 1
        if len(self._models) > model > -1:
            model_name = self._models[model]
            phrase = self.SEP.join(self._phrases.get(model_name, ()))
            msg = phrase and ': "{}"'.format(phrase)
        else:
            model_name, phrase = str(model), ''
            msg = ': "model id out of range: {} > {}"'.format(model, len(self._models) - 1)
        return model_name, phrase, msg

    def msg_parse(self, text: str, phrases: str) -> tuple:
        if self.no_models:
            return self._EMPTY, text
        text2 = self._prep_text(text)
        for phrase in phrases.split(self.SEP):
            offset = text2.find(self._prep_text(phrase))
            if offset > -1:
                return phrase, text[offset + len(phrase):].lstrip(self.STRIP)
        return None, None

    def text_processing(self, text, candidate=None):
        if not (text and isinstance(text, str)) or self.no_models:
            return None
        text2 = self._prep_text(text)
        if candidate:
            model, phrase, _ = candidate
            offset = text2.find(self._prep_text(phrase))
            if offset > -1:
                result = text[offset + len(phrase):].lstrip(self.STRIP)
                if result:
                    return model, phrase, result

        for model, phrases in self._opt_phrases.items():
            for id_, phrase in enumerate(phrases):
                offset = text2.find(phrase)
                if offset > -1:
                    phrase = self._phrases[model][id_]
                    return model, phrase, text[offset + len(phrase):].lstrip(self.STRIP)
        return None

    @staticmethod
    def _prep_text(text: str) -> str:
        return ' ' + ''.join(' ' if x in ',.!?' else x for x in text.lower().replace('ё', 'е')) + ' '
