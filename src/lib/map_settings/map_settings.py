from default_settings import CFG as CFG_CFG
from lib.map_settings.cfg import CFG_DSC, INTERFACES


def make_map_settings(wiki: dict) -> dict:
    return {key: make_interface(value, wiki)for key, value in INTERFACES.items()}


def make_interface(sections: tuple, wiki: dict) -> dict:
    return {key: make_section(CFG_CFG.get(key, {}), CFG_DSC.get(key, {}), wiki.get(key, {})) for key in sections}


def make_section(cfg: dict, dsc: dict, wiki: dict) -> dict:
    result = {key: make_param(key, value, wiki.get(key), dsc.get(key, {})) for key, value in cfg.items()}
    if 'null' in wiki:
        result['description'] = wiki['null']
    return result


def make_param(key: str, value, desc: str, dsc: dict) -> dict:
    # name: {'name': h_name, 'desc': description, 'type': type_, 'default': value}
    # options - optional
    desc = desc or 'description'

    options = dsc.get('options')
    if callable(options):
        options = options()
    if isinstance(options, (set, frozenset)):
        options = list(options)
    elif isinstance(options, dict):
        options = list(options.keys())
    elif not isinstance(options, (list, tuple)):
        options = None

    if options:
        type_ = 'select'
    elif 'type' in dsc:
        type_ = str(dsc['type'])
    elif isinstance(value, bool):
        type_ = 'checkbox'
    else:
        type_ = 'text'

    name = dsc.get('name') or key
    result = {'name': name, 'desc': desc, 'type': type_, 'default': value}
    if options:
        result['options'] = options
    return result
