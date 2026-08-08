"""Action builders for Kaggriculture farmer, hand, and market ops."""


class Actions:
    # --- Movement ---

    @staticmethod
    def north():
        return ["NORTH"]

    @staticmethod
    def south():
        return ["SOUTH"]

    @staticmethod
    def east():
        return ["EAST"]

    @staticmethod
    def west():
        return ["WEST"]

    @staticmethod
    def pass_():
        return ["PASS"]

    # --- Shed / inventory ---

    @staticmethod
    def pickup(item, n=1):
        return ["PICKUP", item, n]

    @staticmethod
    def place(item, n=1):
        return ["PLACE", item, n]

    @staticmethod
    def drop():
        return ["DROP"]

    # --- Plants ---

    @staticmethod
    def plant(crop):
        return ["PLANT", crop]

    @staticmethod
    def water():
        return ["WATER"]

    @staticmethod
    def harvest():
        return ["HARVEST"]

    @staticmethod
    def fertilize():
        return ["FERTILIZE"]

    # --- Animals / structures ---

    @staticmethod
    def build_coop():
        return ["BUILD_COOP"]

    @staticmethod
    def build_pasture():
        return ["BUILD_PASTURE"]

    @staticmethod
    def feed():
        return ["FEED"]

    @staticmethod
    def collect_fertilizer():
        return ["COLLECT_FERTILIZER"]

    @staticmethod
    def care():
        return ["CARE"]

    # --- Terrain ---

    @staticmethod
    def dig():
        return ["DIG"]

    # --- Market ---

    @staticmethod
    def buy_seed(crop, n=1):
        return ["BUY_SEED", crop, n]

    @staticmethod
    def buy_product(item, n=1):
        return ["BUY_PRODUCT", item, n]

    @staticmethod
    def buy_animal(animal, n=1):
        return ["BUY_ANIMAL", animal, n]

    @staticmethod
    def sell(item, n=1):
        return ["SELL", item, n]

    @staticmethod
    def hire():
        return ["HIRE"]

    @staticmethod
    def buy_land():
        return ["BUY_LAND"]
