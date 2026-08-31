from pprint import pprint

from fortrade_browser import (
    get_account,
    get_quotes,
    get_quote,
    get_visible_chart,
)


print("\nACCOUNT")
pprint(get_account())

print("\nALL QUOTES")
pprint(get_quotes())

print("\nGBP/USD")
pprint(get_quote("GBP/USD"))

print("\nVISIBLE CHART")
pprint(get_visible_chart())