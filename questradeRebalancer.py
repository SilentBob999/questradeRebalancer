#!/bin/env python3

import argparse
import json
from sys import float_info
from QuestradeApi import QuestradeApi

AUTH_TOKEN = ""

QUESTRADE_ECN = 0.0035
DOLLAR_COST_AVERAGE = 1.0

questrade_api = QuestradeApi(AUTH_TOKEN)

DEFAULT_TARGET_RATIO_FILE = "target_ratio.json"

sample_ratios = {
    'Margin': {'VCN.TO': 40, 'XUU.TO': 40, 'XEF.TO': 20},
    'TFSA': {'VCN.TO': 40, 'XUU.TO': 40, 'XEF.TO': 20},
    'RRSP': {'VCN.TO': 40, 'XUU.TO': 40, 'XEF.TO': 20}
}


def _read_target_ratio_file(path):
    with open(path, 'r') as f:
        return json.load(f)


def _write_target_ratio_file(ratios_dict, path):
    with open(path, 'w') as f:
        json.dump(ratios_dict, f, indent=4, sort_keys=True)
        f.write('\n')


def get_account_targets(path):
    try:
        return _read_target_ratio_file(path)
    except FileNotFoundError:
        target_ratios = sample_ratios
        _write_target_ratio_file(target_ratios, DEFAULT_TARGET_RATIO_FILE)
        return target_ratios


def get_symbol_target_ratios_for_account(target_ratios, account_type):
    # Please make sure each account adds to 100
    # or this script will not work correctly!
    return target_ratios[account_type]


def get_available_cash(account_id):
    balances = questrade_api.get_balances(account_id)
    cash_balances = balances['perCurrencyBalances']
    for currency in cash_balances:
        if currency['currency'] == 'CAD':
            return currency['cash']


def get_positions_value(account_id, symbols):
    # Initialize dict to have 0 for each symbol
    positions_value = {symbol: 0 for symbol in symbols}
    positions_total = 0
    positions = questrade_api.get_positions(account_id)
    for position in positions['positions']:
        symbol = position['symbol']
        if symbol in symbols:
            value = position['currentMarketValue'] * 1.0
            positions_value[symbol] = value
            positions_total += value
    return positions_total, positions_value


def get_internal_symbols(symbols):
    symbol_id_dicts = {}
    for symbol in symbols:
        symbol_id = questrade_api.get_id_from_symbol_name(symbol)
        symbol_id_dicts[symbol] = symbol_id
    return symbol_id_dicts


def get_symbol_quotes(symbol_ids):
    quotes = questrade_api.get_market_quotes(symbol_ids)
    return {quote['symbol']: quote['askPrice'] for quote in quotes['quotes']}


def new_smallest_symbol(positions_total, target_ratios,
                        symbol_quotes, positions_value):

    def calc_r2(ratio1, ratio2):
        diff = ratio1 - ratio2
        return diff ** 2

    def calc_current_r2(symbol):
        current_ratio = positions_value[symbol] / (positions_total * 1.0)
        target_ratio = target_ratios[symbol] / 100.0
        return calc_r2(current_ratio, target_ratio)

    def calc_new_r2(symbol):
        new_ratio = (positions_value[symbol] + symbol_quotes[symbol]) / \
                    (positions_total + symbol_quotes[symbol] * 1.0)
        target_ratio = target_ratios[symbol] / 100.0
        return calc_r2(new_ratio, target_ratio)

    def calc_r2_diff(symbol):
        curr_r2 = calc_current_r2(symbol)
        new_r2 = calc_new_r2(symbol)
        return new_r2 - curr_r2

    r2_diffs = {symbol: calc_r2_diff(symbol)
                for symbol in positions_value.keys()}
    return min(r2_diffs, key=r2_diffs.get)


def old_smallest_symbols(positions_total, target_ratios,
                         symbol_quotes, positions_value):
    min_mag_diff = float_info.max
    min_symbol = None

    for selected_symbol in target_ratios.keys():
        total = positions_total + symbol_quotes[selected_symbol]

        sum_of_mag_diff = 0
        for symbol, position_value in positions_value.items():
            value = position_value
            if selected_symbol == symbol:
                value += symbol_quotes[selected_symbol]
            diff = (target_ratios[symbol] / 100.0) - (value / total)
            sum_of_mag_diff += diff * diff

        if sum_of_mag_diff < min_mag_diff:
            min_mag_diff = sum_of_mag_diff
            min_symbol = selected_symbol

    return min_symbol


# TODO: maybe
def some_tax_loss_harvest():
    pass


# Buy the stock that will minimize the r^2 between current positions ratios and
# target ratios
def something_strategy_1(cash_total, positions_total, target_ratios,
                         symbol_quotes, positions_value):
    to_buy = {}
    remaining = cash_total

    while remaining > QUESTRADE_ECN:
        # Buy the stock which will produce the smallest difference in ratios
        # TODO: Test out the two different symbol strategies
        symbol = old_smallest_symbols(
            positions_total, target_ratios, symbol_quotes, positions_value)
        # Stop if we can't afford the optimum stock
        if not symbol or (symbol_quotes[symbol] + QUESTRADE_ECN) > remaining:
            break
        to_buy[symbol] = to_buy.get(symbol, 0) + 1
        cost_of_symbol = symbol_quotes[symbol]
        remaining -= cost_of_symbol + QUESTRADE_ECN
        positions_total += cost_of_symbol
        positions_value[symbol] += cost_of_symbol

    # Convert into an order list
    order_list = []
    for symbol, quantity in to_buy.items():
        order = {
            'symbol': symbol,
            'quantity': to_buy[symbol],
            'price': symbol_quotes[symbol],
            'action': 'buy'
        }
        order_list.append(order)
    return order_list


# Buy stocks that will minimize the r^2 just from the total cash.
def something_strategy_2(cash_total, target_ratios, symbol_quotes):
    zeroed_positions = {symbol: 0 for symbol in target_ratios.keys()}
    return something_strategy_1(cash_total, 0, target_ratios,
                                symbol_quotes, zeroed_positions)


# TODO: implement
# Buy and sell to rebalance the portfolio
def something_strategy_3(cash_total, positions_total, target_ratios,
                         symbol_quotes, positions_value):
    return []


def contains_open_conflicting_order(account_id, symbols, verbose=True):
    open_orders = questrade_api.get_orders(account_id, stateFilter='Open')
    conflicting_symbols = []
    for order in open_orders['orders']:
        symbol = order['symbol']
        if symbol in symbols:
            conflicting_symbols.append(symbol)
    if len(conflicting_symbols) == 0:
        return True
    else:
        if verbose:
            for symbol in conflicting_symbols:
                print("There is an open order for {}".format(symbol))
            print("On account".format(account_id))
        return False


# TODO: prioritize sell on strategy 3, don't buy until sold
def place_orders(account_id, order_list):
    for order in order_list:
        symbol = order['symbol']
        quantity = order['quantity']
        price = order['price']
        action = order['action']
        buy = action == "buy"
        po = questrade_api.place_order(account_id, symbol,
                                       quantity, price, buy=buy)
        if po['orders'][0]['rejectReason']:
            reason = po['orders'][0]['rejectReason']
            msg = "Order for {} ({} x {}) was rejected. Reason: {}"
            print(msg.format(symbol, quantity, price, reason))
            break


def preview_order(order):
    symbol = order['symbol']
    quantity = order['quantity']
    price = order['price']
    action = order['action']
    print("{} {} ({} x {})".format(action, symbol, quantity, price))


def something_rebalance(account_id, target_ratios, strategy=1, preview_only=False, confirm=True):
    # Check if there are conflicting orders
    symbols = target_ratios.keys()
    if contains_open_conflicting_order(account_id, symbols, verbose=True):
        return

    cash_total = get_available_cash(account_id) / DOLLAR_COST_AVERAGE
    positions_total, positions_value = get_positions_value(account_id, symbols)
    symbol_quotes = get_symbol_quotes(list(target_ratios.values()))

    # Get orders
    if strategy == 1:
        buy_orders = \
            something_strategy_1(cash_total, positions_total, target_ratios,
                                 symbol_quotes, positions_value)
    elif strategy == 2:
        buy_orders = \
            something_strategy_2(cash_total, target_ratios, symbol_quotes)
    elif strategy == 3:
        buy_orders = \
            something_strategy_3(cash_total, positions_total, target_ratios,
                                 symbol_quotes, positions_value)
    else:
        buy_orders = []

    # Preview orders
    for order in buy_orders:
        preview_order(order)

    # Place orders
    if not preview_only:
        if not confirm:
            confirmed = True
        else:
            keyword = "CONFIRM"
            msg = "Please type {} in all CAPS to place orders: ".format(keyword)
            confirm_in = input(msg)
            confirmed = confirm_in == keyword

        if not confirmed:
            print("Couldn't confirm confirmation. Stopping")
            exit(1)
        place_orders(account_id, buy_orders)


text = {
    'description': 'Buy and sell ETFs/stocks according to the configured ratios.',
    'help': {
        'listAccounts': 'List your Questrade accounts.',
        'showOrders': 'Shows the orders that will be made.',
        'accountType': 'Get the type of the account',
        'accountNumber': 'Get the account number',
        # pending
        'placeOrders': 'Place orders to rebalance the portfolio',
        '--noconfirm': 'Skip the place order confirmation',
        '--noignore': 'Ignore the ignored ETFs/stocks'
    }
}


parser = argparse.ArgumentParser(description=text['description'])
subparsers = parser.add_subparsers(dest='command')
listAccounts = subparsers.add_parser('listAccounts', help=text['help']['listAccounts'])
showOrders = subparsers.add_parser('showOrders', help=text['help']['showOrders'])
showOrders.add_argument('accountType', help=text['help']['accountType'])
showOrders.add_argument('accountNumber', help=text['help']['accountNumber'])
placeOrders = subparsers.add_parser('placeOrders', help=text['help']['placeOrders'])
placeOrders.add_argument('--noconfirm', action='store_true', help=text['help']['--noconfirm'])
placeOrders.add_argument('accountType', help=text['help']['accountType'])
placeOrders.add_argument('accountNumber', help=text['help']['accountNumber'])
args = parser.parse_args()

def main():
    if args.command == 'listAccounts':
        accounts = questrade_api.get_accounts()
        for acc in accounts:
            print(acc['type'], acc['number'])


if args.command == 'listAccounts':
    accounts = questrade_api.get_accounts()
    for acc in accounts['accounts']:
        print(acc['type'], acc['number'])
        exit(0)
else:
    shouldPlaceOrders = args.command == 'placeOrders'
    shouldConfirmOrders = True
    if shouldPlaceOrders:
        shouldConfirmOrders = not args.noConfirm
    accountType = args.accountType
    accountNumber = args.accountNumber

    rebalance(
        accountNumber,
        get_symbol_target_ratios_for_account(accountType),
        shouldPlaceOrders,
        shouldConfirmOrders)

