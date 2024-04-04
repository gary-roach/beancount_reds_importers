"""SCB Credit .csv importer."""

import re

from beancount.core.number import D

from beancount_reds_importers.libreader import csvreader
from beancount_reds_importers.libtransactionbuilder import banking


class Importer(csvreader.Importer, banking.Importer):
    IMPORTER_NAME = "SCB Card CSV"

    def custom_init(self):
        self.max_rounding_error = 0.04
        self.filename_pattern_def = "CardTransactions[0-9]*"
        self.header_identifier = self.config.get(
            "custom_header", "PRIORITY BANKING VISA INFINITE CARD"
        )
        self.column_labels_line = "Date,DESCRIPTION,Foreign Currency Amount,SGD Amount"
        self.date_format = "%d/%m/%Y"
        self.skip_tail_rows = 6
        self.skip_comments = "# "
        # fmt: off
        self.header_map = {
            "Date":         "date",
            "DESCRIPTION":  "payee",
        }
        # fmt: on
        self.transaction_type_map = {}

    def deep_identify(self, file):
        account_number = self.config.get("account_number", "")
        return re.match(self.header_identifier, file.head()) and account_number in file.head()

    def skip_transaction(self, row):
        return "[UNPOSTED]" in row.payee

    def prepare_table(self, rdr):
        rdr = rdr.select(lambda r: "UNPOSTED" not in r["DESCRIPTION"])

        # parse foreign_currency amount: "YEN 74,000"
        if self.config.get("convert_currencies", False):
            # Currency conversions won't work as expected since Beancount v2
            # doesn't support adding @@ (total price conversions) via code.
            # See https://groups.google.com/g/beancount/c/nMvuoR4yOmM
            # This means the '@' generated by this code below needs to be replaced with an '@@'

            rdr = rdr.capture(
                "Foreign Currency Amount",
                "(.*) (.*)",
                ["foreign_currency", "foreign_amount"],
                fill=" ",
                include_original=True,
            )
        rdr = rdr.cutout("Foreign Currency Amount")

        # parse SGD Amount: "SGD 141.02 CR" into a single amount column
        rdr = rdr.capture("SGD Amount", "(.*) (.*) (.*)", ["currency", "amount", "crdr"])

        # change DR into -ve. TODO: move this into csvreader or csvreader.utils
        crdrdict = {"DR": "-", "CR": ""}
        rdr = rdr.convert("amount", lambda i, row: crdrdict[row.crdr] + i, pass_row=True)

        rdr = rdr.addfield("memo", lambda x: "")  # TODO: make this non-mandatory in csvreader
        return rdr

    def prepare_raw_file(self, rdr):
        # Strip tabs and spaces around each field in the entire file
        rdr = rdr.convertall(lambda x: x.strip(" \t") if isinstance(x, str) else x)

        # Delete empty rows
        rdr = rdr.select(lambda x: any([i != "" for i in x]))
        return rdr

    def get_balance_statement(self, file=None):
        """Return the balance on the first and last dates"""
        date = self.get_balance_assertion_date()
        if date:
            balance_row = self.get_row_by_label(file, "Current Balance")
            currency, amount = balance_row[1], balance_row[2]
            units, debitcredit = amount.split()
            if debitcredit != "CR":
                units = "-" + units

            yield banking.Balance(date, D(units), currency)
