def va_render_mapchoicevalue(field_id, value, choice_mapping):
    if field_id not in choice_mapping:
        return value
    if isinstance(value, str) and " " in value:
        choices = value.split(" ")
        mapped_choices = []
        for choice in choices:
            if choice in choice_mapping[field_id]:
                mapped_choices.append(choice_mapping[field_id][choice])
            else:
                mapped_choices.append(choice)
        return ", ".join(mapped_choices)
    else:
        if str(value) in choice_mapping[field_id]:
            return choice_mapping[field_id][str(value)]
        else:
            return value
