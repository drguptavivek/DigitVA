"""Site serializers."""


def serialize_site(site):
    return {
        "site_id": site.site_id,
        "site_name": site.site_name,
        "site_abbr": site.site_abbr,
        "status": site.site_status.value,
    }
