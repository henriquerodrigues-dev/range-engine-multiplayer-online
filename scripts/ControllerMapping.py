"""ControllerMapping - le o teclado e publica o input do personagem em propriedades.

Publica 'input_x', 'input_y', 'input_run' e 'input_jump'. O CharacterController usa
essas propriedades quando existem e cai no WASD embutido quando nao existem, entao
este componente e opcional.

Coloque-o ANTES do CharacterController na lista de componentes do objeto, senao o
input chega com um frame de atraso.

As teclas aceitam nome amigavel ("W", "SPACE", "LEFT SHIFT", "UP", "5") ou o nome da
constante de Range.events ("WKEY", "SPACEKEY", "LEFTSHIFTKEY").
"""

from collections import OrderedDict

from Range import events, logic, types


class ControllerMapping(types.KX_PythonComponent):

    args = OrderedDict([
        # Componente
        ("Activate", True),
        ("Debug", False),

        # Movimento
        ("Forward Key", "W"),
        ("Backward Key", "S"),
        ("Left Key", "A"),
        ("Right Key", "D"),

        # Acoes
        ("Run Key", "LEFT SHIFT"),
        ("Jump Key", "SPACE"),
    ])

    ALIASES = {
        "SHIFT": "LEFTSHIFTKEY",
        "LEFT SHIFT": "LEFTSHIFTKEY",
        "RIGHT SHIFT": "RIGHTSHIFTKEY",
        "CTRL": "LEFTCTRLKEY",
        "CONTROL": "LEFTCTRLKEY",
        "LEFT CTRL": "LEFTCTRLKEY",
        # A API nomeia este sem o sufixo KEY, ao contrario de todos os outros.
        "RIGHT CTRL": "RIGHTCTRL",
        "ALT": "LEFTALTKEY",
        "LEFT ALT": "LEFTALTKEY",
        "RIGHT ALT": "RIGHTALTKEY",
        "SPACE": "SPACEKEY",
        "SPACEBAR": "SPACEKEY",
        "ENTER": "ENTERKEY",
        "RETURN": "RETKEY",
        "TAB": "TABKEY",
        "ESC": "ESCKEY",
        "ESCAPE": "ESCKEY",
        "BACKSPACE": "BACKSPACEKEY",
        "DELETE": "DELKEY",
        "CAPSLOCK": "CAPSLOCKKEY",
        "UP": "UPARROWKEY",
        "DOWN": "DOWNARROWKEY",
        "LEFT": "LEFTARROWKEY",
        "RIGHT": "RIGHTARROWKEY",
        "PAGEUP": "PAGEUPKEY",
        "PAGEDOWN": "PAGEDOWNKEY",
        "0": "ZEROKEY",
        "1": "ONEKEY",
        "2": "TWOKEY",
        "3": "THREEKEY",
        "4": "FOURKEY",
        "5": "FIVEKEY",
        "6": "SIXKEY",
        "7": "SEVENKEY",
        "8": "EIGHTKEY",
        "9": "NINEKEY",
    }

    BINDINGS = (
        ("forward", "Forward Key"),
        ("backward", "Backward Key"),
        ("left", "Left Key"),
        ("right", "Right Key"),
        ("run", "Run Key"),
        ("jump", "Jump Key"),
    )

    def start(self, args):
        self.active = args["Activate"]
        self.debug = args["Debug"]
        self.last_input = None

        unresolved = []
        for attr, arg in self.BINDINGS:
            name = args[arg]
            code = self.resolveKey(name)
            setattr(self, attr, code)
            if code is None and str(name).strip():
                unresolved.append("%s='%s'" % (arg, name))

        if unresolved:
            print("[ControllerMapping] tecla nao reconhecida: %s" % ", ".join(unresolved))

        # Publica desde o start para o CharacterController nao usar o fallback num frame.
        self.publish(0, 0, False, False)

        if self.debug:
            for attr, arg in self.BINDINGS:
                code = getattr(self, attr)
                self.log("%-13s -> %s" % (arg, self.keyName(code)))

    def log(self, message):
        print("[ControllerMapping] %s" % message)

    def resolveKey(self, name):
        """Aceita nome amigavel ou o nome da constante. Retorna None se nao existir."""
        raw = str(name).strip().upper()
        if not raw:
            return None

        compact = raw.replace(" ", "").replace("_", "")
        candidates = []

        alias = self.ALIASES.get(raw) or self.ALIASES.get(compact)
        if alias:
            candidates.append(alias)
        candidates.append(compact)
        candidates.append(compact + "KEY")

        for candidate in candidates:
            code = getattr(events, candidate, None)
            # Validar contra keyboard.inputs descarta as constantes de mouse, que
            # existem em Range.events como int mas nao sao teclas.
            if isinstance(code, int) and code in logic.keyboard.inputs:
                return code

        return None

    def keyName(self, code):
        if code is None:
            return "(nao mapeado)"
        for name in dir(events):
            if not name.startswith("_") and getattr(events, name) == code:
                return name
        return str(code)

    def held(self, code):
        return code is not None and bool(logic.keyboard.inputs[code].active)

    def pressed(self, code):
        if code is None:
            return False
        return logic.KX_INPUT_JUST_ACTIVATED in logic.keyboard.inputs[code].queue

    def publish(self, x, y, run, jump):
        self.object["input_x"] = x
        self.object["input_y"] = y
        self.object["input_run"] = run
        self.object["input_jump"] = jump

    def update(self):
        if not self.active:
            return

        x = int(self.held(self.right)) - int(self.held(self.left))
        y = int(self.held(self.forward)) - int(self.held(self.backward))
        run = self.held(self.run)
        jump = self.pressed(self.jump)

        self.publish(x, y, run, jump)

        if self.debug:
            current = (x, y, run, jump)
            if current != self.last_input:
                self.log("x=%+d y=%+d run=%s jump=%s" % (x, y, run, jump))
                self.last_input = current
