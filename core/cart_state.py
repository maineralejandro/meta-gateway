import warnings

from core.capabilities.cart import CartCapability


class CartState(CartCapability):
    pass


with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    cart_state = CartState()
