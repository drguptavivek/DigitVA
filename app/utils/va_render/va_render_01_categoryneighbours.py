def va_render_categoryneighbours(va_categorylist, va_currentcategory):
    try:
        index = va_categorylist.index(va_currentcategory)
    except ValueError:
        return None, None
    va_prevcategory = va_categorylist[index - 1] if index > 0 else None
    va_nextcategory = (
        va_categorylist[index + 1] if index < len(va_categorylist) - 1 else None
    )
    return va_prevcategory, va_nextcategory
