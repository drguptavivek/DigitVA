"""Shared blueprint objects for data-management routes."""

import logging

from flask import Blueprint


data_management = Blueprint("data_management", __name__)
log = logging.getLogger(__name__)
