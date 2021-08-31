from collections import namedtuple


def pretty(d, indent=0):
    for key, value in d.items():
        print('\t' * indent + str(key))
        if isinstance(value, dict):
            pretty(value, indent + 1)
        else:
            print('\t' * (indent + 1) + str(value))


def parse_obj_to_dict(obj):
    _dict = {}
    members = [attr for attr in dir(obj) if not callable(attr) and not attr.startswith("__")]
    for member in members:
        val = getattr(obj, member)
        if isinstance(val, list):
            _dict[member] = parse_obj_list_to_dict_list(val)
        elif 'binance' in val.__class__.__module__:
            _dict[member] = parse_obj_to_dict(val)
        else:
            _dict[member] = val
    return _dict


def parse_obj_list_to_dict_list(obj_list):
    _list = []
    for obj in obj_list:
        _dict = parse_obj_to_dict(obj)
        _list.append(_dict)
    return _list


def parse_dict_to_obj(dictionary):
    return namedtuple("DoraBotSettings", dictionary.keys())(*dictionary.values())
