import re

from ..vecorel.extensions import ADMIN_DIVISION


class AdminConverterMixin:
    """
    Add admin columns to the dataset
    """

    admin_country_code = None
    admin_subdivision_code = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.admin_country_code is None:
            # Taking country code from ID
            self.admin_country_code = self.id.split("_")[0].upper()
        assert re.match("^[A-Z]{2}$", self.admin_country_code), (
            f"Country code should be 2 uppercase letters, not {self.admin_country_code}"
        )

        self.extensions.add(ADMIN_DIVISION)
        self.column_additions["admin:country_code"] = self.admin_country_code
        self.columns["admin:country_code"] = "admin:country_code"

        if self.admin_subdivision_code:
            self.columns["admin:subdivision_code"] = "admin:subdivision_code"
            self.column_additions["admin:subdivision_code"] = self.admin_subdivision_code
