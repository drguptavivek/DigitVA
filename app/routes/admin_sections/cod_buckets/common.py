"""Shared helpers for COD bucket admin routes."""

import re


def _cod_bucket_node_path_label(node):
    labels = [node.node_label]
    parent = node.parent
    while parent is not None:
        labels.append(parent.node_label)
        parent = parent.parent
    return " > ".join(reversed(labels))


def _cod_bucket_slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "node"
