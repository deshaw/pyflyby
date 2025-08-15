


import os
import pytest
from   shutil                   import rmtree
import sys
from   tempfile                 import mkdtemp
from   textwrap                 import dedent

from   pyflyby                  import Filename, xreload
from   pyflyby._livepatch       import UnknownModuleError


def maybe_dedent(docstring):
    if sys.version_info >= (3, 13):
        # Python 3.13 dedents docstrings
        # https://github.com/python/cpython/issues/81283
        return dedent(docstring)
    return docstring


@pytest.fixture
def tpp(request):
    """
    A temporary directory which is temporarily added to sys.path.
    """
    d = mkdtemp(prefix="pyflyby_test_livepatch_", suffix=".tmp")
    d = Filename(d).real
    def cleanup():
        # Unload temp modules.
        for name, module in sorted(sys.modules.items()):
            if (getattr(module, "__file__", None) or "").startswith(str(d)):
                del sys.modules[name]
        # Clean up sys.path.
        sys.path.remove(str(d))
        # Clean up directory on disk.
        rmtree(str(d))
    request.addfinalizer(cleanup)
    sys.path.append(str(d))
    return d


def writetext(filename, text, mode='w'):
    text = dedent(text)
    assert isinstance(filename, Filename)
    with open(str(filename), mode) as f:
        f.write(text)
    return filename


def test_xreload_1(tpp):
    # Verify basic xreload() functionality.
    writetext(tpp/"sandpiper48219874.py", """
        def foo():
            return 14867117
    """)
    from sandpiper48219874 import foo
    assert foo() == 14867117
    writetext(tpp/"sandpiper48219874.py", """
        def foo():
            return 27906681
    """)
    assert foo() == 14867117
    xreload("sandpiper48219874")
    assert foo() == 27906681


def test_xreload_livepatch_module_1(tpp):
    # Verify that when livepatching, names refer to the same object.
    writetext(tpp/"infomercial40679768.py", """
        def hurricane(): return 18721705
    """)
    import infomercial40679768 as m1
    hurricane = m1.hurricane
    assert hurricane() == 18721705
    writetext(tpp/"infomercial40679768.py", """
        def hurricane(): return 27016395
    """)
    xreload("infomercial40679768")
    assert hurricane is m1.hurricane
    assert hurricane() == 27016395
    import infomercial40679768 as m2
    assert m1 is m2


def test_xreload_repeat_1(tpp):
    # Verify behavior of xreload() called multiple times.
    writetext(tpp/"pilgrim85675962.py", """
        def blouse():
            return 17708918
    """)
    from pilgrim85675962 import blouse
    assert blouse() == 17708918
    writetext(tpp/"pilgrim85675962.py", """
        def blouse():
            return 28724726
    """)
    xreload("pilgrim85675962")
    assert blouse() == 28724726
    writetext(tpp/"pilgrim85675962.py", """
        def blouse():
            return 32649017
    """)
    xreload("pilgrim85675962")
    assert blouse() == 32649017
    writetext(tpp/"pilgrim85675962.py", """
        def blouse():
            return 44667737
    """)
    xreload("pilgrim85675962")
    assert blouse() == 44667737


def test_xreload_by_module_1(tpp):
    # Verify xreload() when passing a module instance (as opposed to a module
    # name as a string).
    writetext(tpp/"symphony64858512.py", """
        def foo():
            return 17004883
    """)
    from symphony64858512 import foo
    assert foo() == 17004883
    writetext(tpp/"symphony64858512.py", """
        def foo():
            return 27410274
    """)
    import symphony64858512
    from symphony64858512 import foo
    assert foo() == 17004883
    xreload(symphony64858512)
    assert foo() == 27410274


def test_xreload_ref_module_1(tpp):
    # Verify that xreload() works correctly when we reference a module rather
    # than a function inside it.
    writetext(tpp/"seabrook33115580.py", """
        def foo():
            return 14237015
    """)
    import seabrook33115580
    assert seabrook33115580.foo() == 14237015
    writetext(tpp/"seabrook33115580.py", """
        def foo():
            return 27952808
    """)
    assert seabrook33115580.foo() == 14237015
    xreload(seabrook33115580)
    assert seabrook33115580.foo() == 27952808


def test_xreload_rel_import_1(tpp):
    # Verify that relative imports work correctly.
    os.mkdir("%s/mizzen31705242"%tpp)
    writetext(tpp/"mizzen31705242/__init__.py", "")
    writetext(tpp/"mizzen31705242/windward.py", """
        from .spray import bar
        def foo():
            return bar()+1
    """)
    writetext(tpp/"mizzen31705242/spray.py", """
        def bar(): return 800
    """)
    from mizzen31705242.windward import foo
    assert foo() == 801
    writetext(tpp/"mizzen31705242/windward.py", """
        from .spray import bar
        def foo():
            return bar()+2
    """)
    assert foo() == 801
    xreload("mizzen31705242.windward")
    assert foo() == 802


def test_xreload_indirect_1(tpp):
    # Verify that xreload() does the right thing when some other module
    # references the reloaded module.
    writetext(tpp/"blackbeard86819829.py", """
        from beachwood55661238 import bar
        def foo():
            return bar() + 1
    """)
    writetext(tpp/"beachwood55661238.py", """
        def bar():
            return 1400
    """)
    from blackbeard86819829 import foo
    assert foo() == 1401
    writetext(tpp/"beachwood55661238.py", """
        def bar():
            return 1500
    """)
    assert foo() == 1401
    xreload("blackbeard86819829")
    assert foo() == 1401
    xreload("beachwood55661238")
    assert foo() == 1501


def test_xreload_init_1(tpp):
    # Verify that xreload() works correctly on __init__.
    os.mkdir("%s/keats67538501"%tpp)
    writetext(tpp/"keats67538501/__init__.py", """
        def foo(): return 1264
    """)
    from keats67538501 import foo
    writetext(tpp/"keats67538501/__init__.py", """
        def foo(): return 2812
    """)
    assert foo() == 1264
    xreload("keats67538501")
    assert foo() == 2812


def test_xreload_pyc_1(tpp):
    # Verify that xreload() works even if the module's __file__ has extension
    # ".pyc".
    writetext(tpp/"frost40788115.py", """
        def foo():
            return 1997613
    """)
    # Import twice.  This is because the first time, __file__ will end in
    # ".py"; the second time, the module's __file__ will end in ".pyc".
    import frost40788115
    del sys.modules['frost40788115']
    del frost40788115
    import frost40788115
    fn = getattr(frost40788115, "__cached__", None) or frost40788115.__file__
    assert fn.endswith(".pyc")
    from frost40788115 import foo
    assert foo() == 1997613
    writetext(tpp/"frost40788115.py", """
        def foo():
            return 23860555
    """)
    xreload("frost40788115")
    assert foo() == 23860555


def test_xreload_pyc_2(tpp):
    writetext(tpp/"flytrap73535781.py", """
        def swift():
            return 1386928
    """)
    import flytrap73535781
    assert flytrap73535781.__file__.endswith(".py")
    flytrap73535781.__file__ += "c"
    from flytrap73535781 import swift
    assert swift() == 1386928
    writetext(tpp/"flytrap73535781.py", """
        def swift():
            return 23430584
    """)
    xreload("flytrap73535781")
    assert swift() == 23430584


def test_xreload_pyo_1(tpp):
    # Verify that xreload() works even if the module's __file__ has extension
    # ".pyo".
    writetext(tpp/"poppyseed80826438.py", """
        def candle():
            return 19667931
    """)
    import poppyseed80826438
    assert poppyseed80826438.__file__.endswith(".py")
    poppyseed80826438.__file__ += "o"
    from poppyseed80826438 import candle
    assert candle() == 19667931
    writetext(tpp/"poppyseed80826438.py", """
        def candle():
            return 29710822
    """)
    xreload("poppyseed80826438")
    assert candle() == 29710822


def test_xreload_new_function_1(tpp):
    # Verify that xreload adds new global functions.
    writetext(tpp/"kitchen77236192.py", """
        def butter(): return 19280380
    """)
    import kitchen77236192 as m
    from kitchen77236192 import butter
    assert m.butter() == butter() == 19280380
    writetext(tpp/"kitchen77236192.py", """
        def butter(): return 27490565
        def garlic(): return 24871212
    """)
    xreload(m)
    assert m.butter() == butter() == 27490565
    assert m.garlic() == 24871212


def test_xreload_remove_function_1(tpp):
    # Verify that xreload removes deleted global functions.
    writetext(tpp/"editor63356121.py", """
        def tissue(): return 13025418
        def paper(): return 17559922
    """)
    import editor63356121 as m
    from editor63356121 import tissue, paper
    assert m.tissue() == tissue() == 13025418
    assert m.paper()  == paper()  == 17559922
    writetext(tpp/"editor63356121.py", """
        def tissue(): return 26005976
    """)
    xreload(m)
    assert m.tissue() == tissue() == 26005976
    assert paper() == 17559922
    assert not hasattr(m, 'paper')


def test_xreload_method_1(tpp):
    # Verify that xreload works on methods of classes.
    writetext(tpp/"forepeak83672583.py", """
        class Bucknell(object):
            def __init__(self, x):
                self.x = x
            def applegate(self):
                return self.x + 1
    """)
    from forepeak83672583 import Bucknell
    x = Bucknell(500)
    writetext(tpp/"forepeak83672583.py", """
        class Bucknell(object):
            def applegate(self):
                return self.x + 2
    """)
    assert x.applegate() == 501
    xreload("forepeak83672583")
    assert x.applegate() == 502


def test_xreload_method_saved_1(tpp):
    # Verify that xreload works on existing references to methods.
    writetext(tpp/"treaty86420758.py", """
        class Sodium(object):
            def __init__(self, x):
                self.x = x
            def chloride(self):
                return self.x + 1
    """)
    from treaty86420758 import Sodium
    chloride = Sodium(300).chloride
    writetext(tpp/"treaty86420758.py", """
        class Sodium(object):
            def chloride(self):
                return self.x + 2
    """)
    assert chloride() == 301
    xreload("treaty86420758")
    assert chloride() == 302


def test_xreload_method_oldstyle_1(tpp):
    # Verify that xreload works on methods of old-style classes.
    writetext(tpp/"melrose62182130.py", """
        class Hooper:
            def __init__(self, x):
                self.x = x
            def wright(self):
                return self.x + 7
    """)
    from melrose62182130 import Hooper
    x = Hooper(500)
    writetext(tpp/"melrose62182130.py", """
        class Hooper:
            def wright(self):
                return self.x + 8
    """)
    assert x.wright() == 507
    xreload("melrose62182130")
    assert x.wright() == 508


def test_xreload_new_method_1(tpp):
    # Verify that adding a method works.
    writetext(tpp/"hologram63376070.py", """
        class Kidney(object):
            pass
    """)
    from hologram63376070 import Kidney
    kidney = Kidney()
    kidney.x = 100
    writetext(tpp/"hologram63376070.py", """
        class Kidney(object):
            def foo(self):
                return self.x*2
    """)
    xreload("hologram63376070")
    assert kidney.foo() == 200


def test_xreload_remove_method_1(tpp):
    # Verify that removing a method works.
    writetext(tpp/"relax30465366.py", """
        class Ostrich:
            def foo(self):
                return 3906331
            def bar(self):
                return 2789681
    """)
    from relax30465366 import Ostrich
    ostrich = Ostrich()
    assert ostrich.foo() == 3906331
    assert ostrich.bar() == 2789681
    writetext(tpp/"relax30465366.py", """
        class Ostrich:
            def bar(self):
                return 2789681
    """)
    xreload("relax30465366")
    assert not hasattr(ostrich, "foo")
    assert ostrich.bar() == 2789681


def test_xreload_remove_overridding_method_1(tpp):
    # Verify that removing an overriding method of a subclass works.
    writetext(tpp/"silverware74732241.py", """
        class Knife(object):
            def foo(self):
                return 'foo k' + self.s
        class ButterKnife(Knife):
            def foo(self):
                return 'foo bk' + self.s
            def bar(self):
                return 'bar bk' + self.s
            def baz(self):
                return 'baz bk' + self.s
    """)
    from silverware74732241 import ButterKnife
    butterknife = ButterKnife()
    butterknife.s = 'x'
    assert butterknife.foo() == "foo bkx"
    assert butterknife.bar() == "bar bkx"
    assert butterknife.baz() == "baz bkx"
    writetext(tpp/"silverware74732241.py", """
        class Knife(object):
            def foo(self):
                return 'foo k' + self.s
        class ButterKnife(Knife):
            def baz(self):
                return 'baz bk' + self.s
    """)
    xreload("silverware74732241")
    assert butterknife.foo() == "foo kx"
    assert not hasattr(butterknife, 'bar')
    assert butterknife.baz() == "baz bkx"


def test_xreload_method_slots_1(tpp):
    # Verify that we can add/remove/modify methods on a class that uses
    # __slots__.
    writetext(tpp/"obstacle79302353.py", """
        class Basketball(object):
            __slots__ = ['x']
            def m1(self): return 13323019
            def m2(self): return 15978688
    """)
    from obstacle79302353 import Basketball
    b = Basketball()
    assert b.m1() == 13323019
    assert b.m2() == 15978688
    writetext(tpp/"obstacle79302353.py", """
        class Basketball(object):
            __slots__ = ['x']
            def m2(self): return 21428789
            def m3(self): return 28023974
    """)
    xreload("obstacle79302353")
    assert not hasattr(b, "m1")
    assert b.m2() == 21428789
    assert b.m3() == 28023974


def test_xreload_method_use_slots_1(tpp):
    # Verify that methods that a modified method's use of slots isn't
    # disrupted.
    writetext(tpp/"awareness57040122.py", """
        class Forehead(object):
            __slots__ = ['x','y']
            def knife(self): return 16990000 + 2*self.x + self.y
    """)
    from awareness57040122 import Forehead
    f = Forehead()
    f.x = 10
    f.y = 3
    assert f.knife() == 16990023
    writetext(tpp/"awareness57040122.py", """
        class Forehead(object):
            __slots__ = ['x','y']
            def knife(self): return 24390000 + 2*self.y + self.x
    """)
    xreload("awareness57040122")
    assert f.knife() == 24390016


def test_xreload_method_slots_changes_1(tpp):
    # Verify that if a class's __slots__ changes, we fallback to not updating.
    writetext(tpp/"outdoor92273440.py", """
        class Innocent(object):
            __slots__ = ['a','b']
            def contact(self): return 13198913
    """)
    import outdoor92273440 as m
    Innocent = m.Innocent
    assert m.Innocent().contact() == 13198913
    assert   Innocent().contact() == 13198913
    writetext(tpp/"outdoor92273440.py", """
        class Innocent(object):
            __slots__ = ['a','b','c']
            def contact(self): return 21411463
    """)
    xreload("outdoor92273440")
    assert m.Innocent().contact() == 21411463
    assert   Innocent().contact() == 13198913


def test_xreload_method_dict_to_slots_1(tpp):
    # Verify that if a class changes from using __dict__ to __slots__, we
    # fallback to not updating methods.
    writetext(tpp/"engage88211816.py", """
        class Reward(object):
            def allegation(self): return 13438023
    """)
    import engage88211816 as m
    Reward = m.Reward
    assert   Reward().allegation() == 13438023
    assert m.Reward().allegation() == 13438023
    writetext(tpp/"engage88211816.py", """
        class Reward(object):
            __slots__ = []
            def allegation(self): return 21350587
    """)
    xreload("engage88211816")
    assert   Reward().allegation() == 13438023
    assert m.Reward().allegation() == 21350587


def test_xreload_method_slots_to_dict_1(tpp):
    # Verify that if a class changes from using __slots__ to __dict__, we
    # fallback to not updating methods.
    writetext(tpp/"favor30667473.py", """
        class Shop(object):
            def commercial(self): return 11155093
    """)
    import favor30667473 as m
    Shop = m.Shop
    assert   Shop().commercial() == 11155093
    assert m.Shop().commercial() == 11155093
    writetext(tpp/"favor30667473.py", """
        class Shop(object):
            __slots__ = []
            def commercial(self): return 23687231
    """)
    xreload("favor30667473")
    assert   Shop().commercial() == 11155093
    assert m.Shop().commercial() == 23687231


def test_xreload_inherited_class_1(tpp):
    # Verify that xreload works on inherited base classes.
    writetext(tpp/"yellowbank8578489.py", """
        class Goulash(object):
            def trick(self): return self.x + 1
    """)
    from yellowbank8578489 import Goulash
    class Drape(Goulash):
        x = 700
    drape = Drape()
    assert drape.trick() == 701
    writetext(tpp/"yellowbank8578489.py", """
        class Goulash(object):
            def trick(self): return self.x + 2
    """)
    xreload("yellowbank8578489")
    assert drape.trick() == 702


def test_xreload_change_inheritance_1(tpp):
    # Verify that xreload works when a class's base (parent) class changes.
    writetext(tpp/"shoulder77076723.py", """
        class A(object):
            def stone(self): return 15197900
        class T(A):
            def rock(self): return self.stone() + 5
    """)
    from shoulder77076723 import T
    t = T()
    assert t.rock() == 15197905
    writetext(tpp/"shoulder77076723.py", """
        class B(object):
            def stone(self): return 23495300
        class T(B):
            def rock(self): return self.stone() + 6
    """)
    xreload("shoulder77076723")
    assert t.rock() == 23495306


def test_xreload_classmethod_1(tpp):
    # Verify that xreload works on classmethods.
    writetext(tpp/"weekday4165008.py", """
        class Monday(object):
            x = 100
            @classmethod
            def afternoon(cls):
                return cls.x + cls.y + 5
    """)
    from weekday4165008 import Monday
    class Moonday(Monday):
        y = 20
    moonday = Moonday()
    afternoon = Moonday.afternoon
    assert moonday.afternoon() == 125
    assert Moonday.afternoon() == 125
    assert         afternoon() == 125
    writetext(tpp/"weekday4165008.py", """
        class Monday(object):
            x = 200
            @classmethod
            def afternoon(cls):
                return cls.x + cls.y + 6
    """)
    xreload("weekday4165008")
    assert moonday.afternoon() == 226
    assert Moonday.afternoon() == 226
    assert         afternoon() == 226


def test_xreload_staticmethod_1(tpp):
    # Verify that xreload works on staticmethods.
    writetext(tpp/"experiment46879233.py", """
        class Molybdenum:
            @staticmethod
            def spread():
                return 18733360
    """)
    from experiment46879233 import Molybdenum
    molybdenum = Molybdenum()
    spread = molybdenum.spread
    assert molybdenum.spread() == 18733360
    assert Molybdenum.spread() == 18733360
    assert            spread() == 18733360
    writetext(tpp/"experiment46879233.py", """
        class Molybdenum:
            @staticmethod
            def spread():
                return 24122717
    """)
    xreload("experiment46879233")
    assert molybdenum.spread() == 24122717
    assert Molybdenum.spread() == 24122717
    assert            spread() == 24122717


def test_xreload_property_1(tpp):
    # Verify that xreload works on properties.
    writetext(tpp/"snail78310145.py", """
        class Harry(object):
            @property
            def moisture(self): return self.x + 100
    """)
    from snail78310145 import Harry
    harry = Harry()
    harry.x = 5
    assert harry.moisture == 105
    writetext(tpp/"snail78310145.py", """
        class Harry(object):
            @property
            def moisture(self): return self.x + 200
    """)
    xreload("snail78310145")
    assert harry.moisture == 205


def test_xreload_nested_class_1(tpp):
    # Verify that xreload works on nested classes.
    writetext(tpp/"fiction48784218.py", """
        class SciFi:
            class Skiffy:
                def sentiment(self): return 13624633
            skiffy = Skiffy()
            def particle(self): return self.Skiffy().sentiment()
    """)
    from fiction48784218 import SciFi
    Skiffy = SciFi.Skiffy
    skiffy = SciFi.skiffy
    assert SciFi().particle()   == 13624633
    assert Skiffy().sentiment() == 13624633
    assert skiffy.sentiment()   == 13624633
    writetext(tpp/"fiction48784218.py", """
        class SciFi:
            class Skiffy:
                def sentiment(self): return 26888093
            skiffy = Skiffy()
            def particle(self): return self.Skiffy().sentiment()
    """)
    xreload("fiction48784218")
    import fiction48784218
    assert SciFi is fiction48784218.SciFi
    assert Skiffy is fiction48784218.SciFi.Skiffy
    assert SciFi().particle()   == 26888093
    assert Skiffy().sentiment() == 26888093
    assert skiffy.sentiment()   == 26888093


def test_xreload_int_1(tpp):
    # Verify that xreload on constants doesn't change imported names, since
    # that's impossible, but at least updates the module member.
    writetext(tpp/"imperato16438270.py", """
        freehold = 10309655
    """)
    import imperato16438270 as m
    from imperato16438270 import freehold
    assert   freehold == 10309655
    assert m.freehold == 10309655
    writetext(tpp/"imperato16438270.py", """
        freehold = 22865923
    """)
    xreload(m)
    assert   freehold == 10309655
    assert m.freehold == 22865923

@pytest.mark.skip
def test_xreload_auto_1(tpp):
    # Verify that xreload() with no args does reload the modified module.
    writetext(tpp/"horsepower50920658.py", """
        def watt():
            return 746
    """)
    from horsepower50920658 import watt
    assert watt() == 746
    writetext(tpp/"horsepower50920658.py", """
        def watt():
            return 745
    """)
    xreload()
    assert watt() == 745


@pytest.mark.skip
def test_xreload_auto_pyc_1(tpp):
    # Verify that xreload() with no args does reload the modified module, even
    # if it was compiled.
    writetext(tpp/"cowpower84929107.py", """
        def watt():
            return 16247534
    """)
    # Import twice to make sure we use the compiled file the second time.
    import cowpower84929107
    del sys.modules['cowpower84929107']
    del cowpower84929107
    import cowpower84929107
    fn = getattr(cowpower84929107, "__cached__", None) or cowpower84929107.__file__
    assert fn.endswith(".pyc")
    from cowpower84929107 import watt
    assert watt() == 16247534
    writetext(tpp/"cowpower84929107.py", """
        def watt():
            return 25685173
    """)
    xreload()
    assert watt() == 25685173


@pytest.mark.skip
def test_xreload_auto_selective_1(tpp):
    # Verify that xreload() doesn't bother reloading files that have been
    # touched but not changed.
    writetext(tpp/"weather10549431.py", """
        def cloud():
            return 1656116
        rain = object()
    """)
    import weather10549431
    rain1 = weather10549431.rain
    from weather10549431 import cloud
    assert cloud() == 1656116
    writetext(tpp/"weather10549431.py", """
        def cloud():
            return 2057859
        rain = object()
    """)
    xreload()
    assert cloud() == 2057859
    rain2 = weather10549431.rain
    assert rain2 is not rain1
    writetext(tpp/"weather10549431.py", """
        def cloud():
            return 2057859
        rain = object()
    """) # same content
    # Call xreload(), and expect that we don't actually xreload weather10549431.
    xreload()
    assert cloud() == 2057859
    rain3 = weather10549431.rain
    # Verify that we didn't reload the module.
    assert rain3 is rain2


def test_xreload_unchanged_1(tpp):
    # Verify that xreload(m) doesn't bother reloading a module that has not
    # changed.
    sys.__counter_23618278 = 0
    writetext(tpp/"workaholic77872472.py", """
        import sys
        sys.__counter_23618278 += 1
        def diagonal():
            return 15046433
    """)
    from workaholic77872472 import diagonal
    assert diagonal() == 15046433
    assert sys.__counter_23618278 == 1
    writetext(tpp/"workaholic77872472.py", """
        import sys
        sys.__counter_23618278 += 1
        def diagonal():
            return 20787575
    """)
    xreload('workaholic77872472')
    assert diagonal() == 20787575
    assert sys.__counter_23618278 == 2
    xreload('workaholic77872472')
    assert sys.__counter_23618278 == 2
    writetext(tpp/"workaholic77872472.py", """
        import sys
        sys.__counter_23618278 += 1
        def diagonal():
            return 20787575
    """) # unchanged
    xreload('workaholic77872472')
    assert sys.__counter_23618278 == 2


def test_xreload_module_doc_1(tpp):
    # Verify that xreload livepatches the module's __doc__.
    writetext(tpp/"brain29321610.py", """
        '''
          hello
          there
        '''
        def f():
            return __doc__ + '!'
    """)
    import brain29321610
    from brain29321610 import f
    assert brain29321610.__doc__ == maybe_dedent("\n  hello\n  there\n")
    assert f() == maybe_dedent("\n  hello\n  there\n") + "!"
    writetext(tpp/"brain29321610.py", """
        '''
          goodbye
          there
        '''
        def f():
            return __doc__ + '?'
    """)
    xreload('brain29321610')
    assert brain29321610.__doc__ == maybe_dedent("\n  goodbye\n  there\n")
    assert f() == maybe_dedent("\n  goodbye\n  there\n") + "?"


def test_xreload_function_doc_1(tpp):
    # Verify that xreload livepatches function and method __doc__s.
    writetext(tpp/"dinner85190349.py", """
        class Weekend(object):
            def date():
                '''
                  abc
                   def
                '''
        def weekday():
            '''
             a
              b
            '''
    """)
    from dinner85190349 import Weekend, weekday
    assert Weekend.date.__doc__ == maybe_dedent("\n          abc\n           def\n        ")
    assert weekday.__doc__ == maybe_dedent("\n     a\n      b\n    ")
    writetext(tpp/"dinner85190349.py", """
        class Weekend(object):
            '''
               ab
                CD
            '''
            def date():
                '''
                  abc
                   DEF
                '''
        def weekday():
            '''
             a
              B
            '''
    """)
    xreload("dinner85190349")
    assert Weekend.date.__doc__ == maybe_dedent("\n          abc\n           DEF\n        ")
    assert weekday.__doc__ == maybe_dedent("\n     a\n      B\n    ")


def test_xreload_class_doc_1(tpp):
    # Verify that xreload livepatches class __doc__s.
    # This is only possible with Python 3.3+ (http://bugs.python.org/issue12773)
    # For earlier versions, at least check that we don't crash.
    writetext(tpp/"experience90592183.py", """
        class Beautiful(object):
            '''
               ab
                cd
            '''
    """)
    from experience90592183 import Beautiful
    assert Beautiful.__doc__ == maybe_dedent("\n       ab\n        cd\n    ")
    writetext(tpp/"experience90592183.py", """
        class Beautiful(object):
            '''
               ab
                CD
            '''
    """)
    xreload("experience90592183")
    assert Beautiful.__doc__ == maybe_dedent("\n       ab\n        CD\n    ")


def test_xreload_function_attribute_1(tpp):
    # Verify that xreload livepatches function attributes.
    writetext(tpp/"anticipation33569662.py", """
        def understanding(): return 15526786
        understanding.a = 10995274
        understanding.b = 11865913
        understanding.f = lambda: 12364324
        understanding.d = {'x':13988657}
    """)
    from anticipation33569662 import understanding
    assert understanding() == 15526786
    assert understanding.a == 10995274
    assert understanding.b == 11865913
    f = understanding.f
    assert f() == 12364324
    d = understanding.d
    assert d['x'] == 13988657
    writetext(tpp/"anticipation33569662.py", """
        def understanding(): return 25575852
        understanding.a = 20176150
        understanding.b = 21829409
        understanding.f = lambda: 22429566
        understanding.d = {'x':23061934}
    """)
    xreload("anticipation33569662")
    assert understanding() == 25575852
    assert understanding.a == 20176150
    assert understanding.b == 21829409
    assert understanding.f is f
    assert f() == 22429566
    assert understanding.d is d
    assert d['x'] == 23061934


def test_xreload_function_attribute_new_1(tpp):
    # Verify that new function attributes get added.
    writetext(tpp/"grief59410253.py", """
        def sigh():
            pass
        sigh.a = 19429915
    """)
    from grief59410253 import sigh
    assert sigh.a == 19429915
    writetext(tpp/"grief59410253.py", """
        def sigh():
            pass
        sigh.a = 27055214
        sigh.b = 20642144
    """)
    xreload("grief59410253")
    assert sigh.a == 27055214
    assert sigh.b == 20642144


def test_xreload_function_attribute_del_1(tpp):
    # Verify that removed function attributes get deleted.
    # (We could consider changing this behavior though.)
    writetext(tpp/"capability13004138.py", """
        def international():
            pass
        international.a = 15959601
        international.b = 13655765
    """)
    from capability13004138 import international
    assert international.a == 15959601
    assert international.b == 13655765
    writetext(tpp/"capability13004138.py", """
        def international():
            pass
        international.a = 22364411
    """)
    xreload("capability13004138")
    from capability13004138 import international
    assert international.a == 22364411
    assert not hasattr(international, 'b')



def test_xreload_class_with_dunder_eq_1(tpp):
    # Verify that having a member object whose __eq__ is not well-behaved
    # doesn't break the xreload functionality.
    writetext(tpp/"passenger21471674.py", """
        class MyArray(object):
            def __eq__(self, o): 1/0
        class Minister(object):
            ary = MyArray()
            def defense(self):
                return 17026497
    """)
    from passenger21471674 import Minister
    minister = Minister()
    assert minister.defense() == 17026497
    minister = Minister()
    writetext(tpp/"passenger21471674.py", """
        class MyArray(object):
            def __eq__(self, o): 1/0
        class Minister(object):
            ary = MyArray()
            def defense(self):
                return 25303564
    """)
    xreload("passenger21471674")
    assert minister.defense() == 25303564


def test_xreload_dict_1(tpp):
    # Verify that xreload livepatches a global dictionary, including functions
    # in the dictionary.
    writetext(tpp/"conviction55423660.py", """
        d = {}
        d['a'] = lambda: 15816833
        d['b'] = lambda: 10473469
    """)
    import conviction55423660
    from conviction55423660 import d
    assert sorted(d.keys()) == ['a','b']
    a = d['a']
    assert a() == 15816833
    assert d['a']() == 15816833
    assert d['b']() == 10473469
    writetext(tpp/"conviction55423660.py", """
        d = {}
        d['a'] = lambda: 25077523
        d['c'] = lambda: 23017542
    """)
    xreload("conviction55423660")
    assert conviction55423660.d is d
    assert conviction55423660.d['a'] is a
    assert sorted(d.keys()) == ['a','c']
    assert d['a']() == 25077523
    assert d['c']() == 23017542
    assert a() == 25077523


def test_xreload_dict_2(tpp):
    # Check dictionaries with non-string keys
    writetext(tpp/"conviction55423660.py", """
        d = {}
        d['one'] = lambda: 2
        d[1] = lambda: 'two'
    """)
    import conviction55423660
    from conviction55423660 import d
    assert sorted(d.keys(), key=str) == [1, 'one']
    a = d['one']
    assert a() == 2
    assert d['one']() == 2
    assert d[1]() == 'two'
    writetext(tpp/"conviction55423660.py", """
        d = {}
        d['one'] = lambda: 2
        d[2] = lambda: 'one'
    """)
    xreload("conviction55423660")
    assert conviction55423660.d is d
    assert conviction55423660.d['one'] is a
    assert sorted(d.keys(), key=str) == [2, 'one']
    assert d['one']() == 2
    assert d[2]() == 'one'
    assert a() == 2


def test_xreload_decorated_1(tpp):
    writetext(tpp/"investigator73085685.py", """
        from contextlib import contextmanager
        @contextmanager
        def detective():
            yield 13810177
    """)
    from investigator73085685 import detective
    with detective() as x:
        assert x == 13810177
    writetext(tpp/"investigator73085685.py", """
        from contextlib import contextmanager
        @contextmanager
        def detective():
            yield 26534866
    """)
    xreload("investigator73085685")
    with detective() as x:
        assert x == 26534866


def test_xreload_function_hook_1(tpp):
    # Verify that __livepatch__ gets called on new function.
    writetext(tpp/"constitution16719090.py", """
        def pillow():
            return 19529112
        pillow.x = 11446168
        pillow.__livepatch__ = lambda old, new: 1/0
    """)
    from constitution16719090 import pillow
    assert pillow() == 19529112
    assert pillow.x == 11446168
    writetext(tpp/"constitution16719090.py", """
        def pillow():
            return 21302441
        def r(old, new, do_livepatch):
            result = do_livepatch()
            result.x = 25736381
            return result
        pillow.__livepatch__ = r
    """)
    xreload("constitution16719090")
    assert pillow() == 21302441
    assert pillow.x == 25736381


def test_xreload_function_hook_parameters_1(tpp):
    # Verify that __livepatch__ gets called with proper 'old' and 'new'
    # parameters.
    sys._ctr17689481 = 21843257
    writetext(tpp/"shopping58712253.py", """
        def vacation():
            return 13901843
    """)
    from shopping58712253 import vacation
    assert vacation() == 13901843
    writetext(tpp/"shopping58712253.py", """
        def vacation():
            return 27046520
        def r(old, new, do_livepatch):
            assert old() == 13901843
            assert new() == 27046520
            result = do_livepatch()
            assert result is old
            assert old() == 27046520
            import sys
            sys._ctr17689481 += 1
            return result
        vacation.__livepatch__ = r
    """)
    xreload("shopping58712253")
    assert vacation() == 27046520
    assert sys._ctr17689481 == 21843258


def test_xreload_function_hook_parameters_reorderd_1(tpp):
    # Verify behavior of __livepatch__ with parameters in different order.
    sys._ctr45913687 = 15151321
    writetext(tpp/"location41284961.py", """
        def activist():
            return 10433877
    """)
    from location41284961 import activist
    assert activist() == 10433877
    writetext(tpp/"location41284961.py", """
        def activist():
            return 25853725
        def r(do_livepatch, old, new):
            assert old() == 10433877
            assert new() == 25853725
            result = do_livepatch()
            assert result is old
            assert old() == 25853725
            import sys
            sys._ctr45913687 += 1
            return result
        activist.__livepatch__ = r
    """)
    xreload("location41284961")
    assert activist() == 25853725
    assert sys._ctr45913687 == 15151322


def test_xreload_function_hook_parameters_positional_1(tpp):
    # Verify behavior of __livepatch__ with first parameter some name
    # other than 'old'.
    writetext(tpp/"lifestyle66609443.py", """
        def riot():
            return 12188608
    """)
    from lifestyle66609443 import riot
    assert riot() == 12188608
    writetext(tpp/"lifestyle66609443.py", """
        def riot():
            return 21818407
        def r(OLDFUNC):
            assert OLDFUNC() == 12188608
            OLDFUNC.__code__ = riot.__code__
            assert OLDFUNC() == 21818407
            return OLDFUNC
        riot.__livepatch__ = r
    """)
    xreload("lifestyle66609443")
    assert riot() == 21818407


def test_xreload_function_hook_no_update_1(tpp):
    # Verify the behavior of a __livepatch__ hook that doesn't update the
    # function.
    writetext(tpp/"balloon3322563.py", """
        def switch():
            return 11803943
    """)
    import balloon3322563
    from balloon3322563 import switch
    assert switch() == 11803943
    assert balloon3322563.switch() == 11803943
    switch.x = 1342071
    writetext(tpp/"balloon3322563.py", """
        def switch():
            return 29230337
        def r(old, new):
            new.__dict__.update(old.__dict__)
            return new
        switch.__livepatch__ = r
    """)
    xreload("balloon3322563")
    assert switch() == 11803943
    assert balloon3322563.switch() == 29230337
    assert balloon3322563.switch.x == 1342071


def test_xreload_module_hook_1(tpp):
    # Verify the behavior of __livepatch__ at the module level.
    writetext(tpp/"industry40918563.py", """
        def a(): return 10
        def b(): return 20
    """)
    import industry40918563
    from industry40918563 import a, b
    assert industry40918563.a() == a() == 10
    assert industry40918563.b() == b() == 20
    writetext(tpp/"industry40918563.py", """
        def a(): return 1000
        def b(): return 2000
        def __livepatch__(old, new):
            # Selectively update ``a`` but not ``b``
            from pyflyby import livepatch
            livepatch(old.a, new.a)
            old.b = new.b
            return old
    """)
    xreload("industry40918563")
    assert industry40918563.a() == 1000
    assert industry40918563.b() == 2000
    assert a() == 1000
    assert b() == 20


def test_xreload_module_hook_update_1(tpp):
    # Verify behavior of a module-level hook that calls do_livepatch().
    sys._ctr44456173 = 34722256
    writetext(tpp/"automobile47846583.py", """
        def car(): return 17484432
    """)
    from automobile47846583 import car
    assert car() == 17484432
    writetext(tpp/"automobile47846583.py", """
        def car(): return 22955416
        def __livepatch__(old, do_livepatch):
            assert old.car() == 17484432
            result = do_livepatch()
            assert old.car() == 22955416
            assert result is old
            import sys
            sys._ctr44456173 += 1
            return result
    """)
    xreload("automobile47846583")
    assert car() == 22955416
    assert sys._ctr44456173 == 34722257


def test_xreload_module_hook_update_parameters_reordered_1(tpp):
    # Verify behavior of a module-level hook with reordered parameters.
    sys._ctr81306964 = 81471351
    writetext(tpp/"authorize82132226.py", """
        def publication(): return 17737780
    """)
    from authorize82132226 import publication
    assert publication() == 17737780
    writetext(tpp/"authorize82132226.py", """
        def publication(): return 28718896
        def __livepatch__(new, do_livepatch, old):
            assert old.publication() == 17737780
            result = do_livepatch()
            assert old.publication() == 28718896
            assert result is old
            import sys
            sys._ctr81306964 += 1
            return result
    """)
    xreload("authorize82132226")
    assert publication() == 28718896
    assert sys._ctr81306964 == 81471352


def test_xreload_module_hook_return_new_1(tpp):
    # Verify behavior of a module-level hook that returns ``new`` instead of
    # ``old``.
    writetext(tpp/"devastation69918044.py", """
        def homeless(): return 17436793
    """)
    import devastation69918044 as m
    homeless = m.homeless
    assert homeless() == 17436793
    assert m.homeless is homeless
    writetext(tpp/"devastation69918044.py", """
        def homeless(): return 23845845
        def __livepatch__(old, new):
            return new
    """)
    xreload(m)
    assert homeless() == 17436793
    assert m.homeless is homeless
    import devastation69918044 as m2
    assert m is not m2
    assert m2.homeless() == 23845845


def test_xreload_module_hook_return_custom_1(tpp):
    # Verify behavior of a module-level hook that returns a new object
    # altogether.
    writetext(tpp/"preparation18869481.py", """
        monkey = 83669400
        def elephant(): return 11490097
    """)
    import preparation18869481 as m1
    elephant = m1.elephant
    assert elephant() == 11490097
    writetext(tpp/"preparation18869481.py", """
        def elephant(): return 26833907
        def __livepatch__(old, new):
            from pyflyby import livepatch
            class FakeModule(object):
                @property
                def monkey(self):
                    old.monkey += 1
                    return old.monkey
                __name__ = "preparation18869481"
                elephant = staticmethod(livepatch(old.elephant, new.elephant))
            return FakeModule()
    """)
    xreload(m1)
    import preparation18869481 as m2
    assert m1.monkey == 83669400
    assert m2.monkey == 83669401
    assert m2.monkey == 83669402
    assert m1.monkey == 83669402
    assert elephant() == 26833907
    assert elephant is m1.elephant
    assert elephant is m2.elephant


def test_xreload_function_closure_1(tpp):
    # Verify that xreload can livepatch a function with a simple change to its
    # closures.
    writetext(tpp/"drunk50672349.py", """
        def whiskey():
            malt = lambda: 1336508000
            return lambda: malt()+1
        scotty = whiskey()
    """)
    import drunk50672349
    from drunk50672349 import scotty
    assert scotty() == 1336508001
    writetext(tpp/"drunk50672349.py", """
        def whiskey():
            malt = lambda: 2861016000
            return lambda: malt()+2
        scotty = whiskey()
    """)
    xreload(drunk50672349)
    assert scotty() == 2861016002
    assert drunk50672349.scotty is scotty


def test_xreload_function_closure_changed_value_1(tpp):
    # Verify that for cases where xreload can't livepatch a closure, it falls
    # back to not updating in place.  If a non-function value changed, it's
    # not possible to livepatch the closure.
    writetext(tpp/"design57290342.py", """
        def makezoo():
            candle = 19372835
            return lambda: candle
        zoo = makezoo()
    """)
    import design57290342 as m
    from design57290342 import makezoo, zoo
    assert m.makezoo()() == 19372835
    assert   makezoo()() == 19372835
    assert       zoo()   == 19372835
    writetext(tpp/"design57290342.py", """
        def makezoo():
            candle = 21581190
            return lambda: candle
        zoo = makezoo()
    """)
    xreload(m)
    assert m.makezoo()() == 21581190
    assert   makezoo()() == 21581190
    assert       zoo()   == 19372835


def test_xreload_function_closure_changed_cell_count_1(tpp):
    # Verify that for cases where xreload can't livepatch a closure, it falls
    # back to not updating in place.  If the number of items changed, it's not
    # possible to livepatch the closure.
    writetext(tpp/"character20416458.py", """
        def makebrave():
            protagonist = lambda: 11220402
            return lambda: protagonist()
        brave = makebrave()
    """)
    import character20416458 as m
    from character20416458 import makebrave, brave
    assert m.makebrave()() == 11220402
    assert   makebrave()() == 11220402
    assert       brave()   == 11220402
    writetext(tpp/"character20416458.py", """
        def makebrave():
            protagonist = lambda: 22277801
            antagonist  = lambda: 28225896
            return lambda: protagonist() if antagonist() > 0 else protagonist()
        brave = makebrave()
    """)
    xreload("character20416458")
    assert m.makebrave()() == 22277801
    assert   makebrave()() == 22277801
    assert       brave()   == 11220402


def test_xreload_memoize_with_hook_keepcache_1(tpp):
    # Verify that a memoized function can be xreloaded.  Verify that we can
    # define a reload hook that keeps the memoization cache.
    sys.__ctr23998030 = 0
    writetext(tpp/"spectrum4723753.py", """
        import sys
        def memoize(function):
            cache = {}
            def wrapped_fn(*args):
                try:
                    return cache[args]
                except KeyError:
                    result = function(*args)
                    cache[args] = result
                    return result
            wrapped_fn.cache = cache
            return wrapped_fn
        @memoize
        def rainbow(a, b):
            sys.__ctr23998030 += 1
            return (a+b, sys.__ctr23998030)
    """)
    from spectrum4723753 import rainbow
    assert rainbow(100,5) == (105, 1)
    assert rainbow(100,6) == (106, 2)
    assert rainbow(100,5) == (105, 1)
    writetext(tpp/"spectrum4723753.py", """
        import sys
        def memoize(function):
            cache = {}
            def wrapped_fn(*args):
                try:
                    return cache[args]
                except KeyError:
                    result = function(*args)
                    cache[args] = result
                    return result
            wrapped_fn.cache = cache
            def my_livepatch(old, new, do_livepatch):
                oldcache = dict(old.cache)
                result = do_livepatch()
                result.cache.update(oldcache)
                return result
            wrapped_fn.__livepatch__ = my_livepatch
            return wrapped_fn
        @memoize
        def rainbow(a, b):
            sys.__ctr23998030 += 1
            return (-(a+b), sys.__ctr23998030)
    """)
    xreload("spectrum4723753")
    assert rainbow(100,7) == (-107, 3)
    assert rainbow(100,5) == (105, 1)
    assert rainbow(100,6) == (106, 2)


def test_xreload_memoize_with_hook_clearcache_1(tpp):
    # Verify that a memoized function can be xreloaded.  Verify that we can
    # define a reload hook that clears the memoization cache.
    sys.__ctr86585005 = 0
    writetext(tpp/"president22721738.py", """
        import sys
        def memoize(function):
            cache = {}
            def wrapped_fn(*args):
                try:
                    return cache[args]
                except KeyError:
                    result = function(*args)
                    cache[args] = result
                    return result
            wrapped_fn.cache = cache
            return wrapped_fn
        @memoize
        def curiosity(a, b):
            sys.__ctr86585005 += 1
            return (a+b, sys.__ctr86585005)
    """)
    from president22721738 import curiosity
    assert curiosity(100,5) == (105, 1)
    assert curiosity(100,6) == (106, 2)
    assert curiosity(100,5) == (105, 1)
    writetext(tpp/"president22721738.py", """
        import sys
        def memoize(function):
            cache = {}
            def wrapped_fn(*args):
                try:
                    return cache[args]
                except KeyError:
                    result = function(*args)
                    cache[args] = result
                    return result
            wrapped_fn.cache = cache
            def my_livepatch(old, new, do_livepatch):
                result = do_livepatch()
                result.cache.clear()
                return result
            wrapped_fn.__livepatch__ = my_livepatch
            return wrapped_fn
        @memoize
        def curiosity(a, b):
            sys.__ctr86585005 += 1
            return (-(a+b), sys.__ctr86585005)
    """)
    xreload("president22721738")
    assert curiosity(100,7) == (-107, 3)
    assert curiosity(100,5) == (-105, 4)
    assert curiosity(100,6) == (-106, 5)


def test_xreload_class_hook_1(tpp):
    writetext(tpp/"signature99720031.py", """
        class Chemical(object):
            def __init__(self, x): self.x = x
            def taste(self): return self.x + 1
        chemical = Chemical(82727000)
    """)
    from signature99720031 import chemical
    assert chemical.taste() == 82727001

    # XXX TODO



def test_xreload_proxy_module_1(tpp):
    # Verify that xreload works on modules that replace themselves with a
    # proxy object.
    sys._ctr87517064 = 100
    writetext(tpp/"application88589868.py", """
        import sys
        def calculate(): return 16259182
        class M(object):
            @property
            def facility(self):
                sys._ctr87517064 += 1
                return sys._ctr87517064
        m = M()
        m.__dict__ = globals()
        m.__name__ = __name__
        m._orig_module = sys.modules[__name__] # prevent gc issue
        sys.modules[__name__] = m
    """)
    from application88589868 import calculate, facility
    assert calculate() == 16259182
    assert facility == 101
    import application88589868
    assert application88589868.calculate() == 16259182
    assert application88589868.facility == 102
    from application88589868 import facility
    assert facility == 103
    writetext(tpp/"application88589868.py", """
        import sys
        def calculate(): return 27074927
        class M(object):
            @property
            def facility(self):
                sys._ctr87517064 += 100
                return sys._ctr87517064
        m = M()
        m.__dict__ = globals()
        m.__name__ = __name__
        m._orig_module = sys.modules[__name__] # prevent gc issue
        sys.modules[__name__] = m
    """)
    xreload("application88589868")
    assert calculate() == 27074927
    assert application88589868.calculate() == 27074927
    assert application88589868.facility == 203
    assert application88589868.facility == 303
    from application88589868 import facility
    assert facility == 403
    assert sys.modules["application88589868"] is application88589868


def test_xreload_restore_after_failure_1(tpp):
    # Verify that if importing fails, we restore the module - even if the
    # module had itself messed with sys.modules.
    writetext(tpp/"soldier45009654.py", """
        import sys
        class M(object):
            @property
            def backyard(self): return 13029999
        m = M()
        m.__name__ = __name__
        m.__file__ = __file__
        m._orig_module = sys.modules[__name__] # prevent gc issue
        sys.modules[__name__] = m
    """)
    import soldier45009654 as m
    assert m.backyard == 13029999
    writetext(tpp/"soldier45009654.py", """
        import sys
        class M(object):
            @property
            def backyard(self): return 29361607
        m = M()
        m.__name__ = __name__
        m.__file__ = __file__
        m._orig_module = sys.modules[__name__] # prevent gc issue
        sys.modules[__name__] = m
        1/0
    """)
    with pytest.raises(ZeroDivisionError):
        xreload("soldier45009654")
    import soldier45009654 as m
    assert m.backyard == 13029999


def test_xreload_ref_cycle_class_1(tpp):
    # Verify that xreload works as expected when there's a reference cycle in
    # the form of a class that references itself.
    writetext(tpp/"fantasy72283663.py", """
        class C(object):
            def f(self): return 12977051
        C.X = C
    """)
    from fantasy72283663 import C
    assert C.X is C
    assert C().f() == 12977051
    writetext(tpp/"fantasy72283663.py", """
        class C(object):
            def f(self): return 24368102
        C.X = C
    """)
    xreload("fantasy72283663")
    assert C.X is C
    assert C().f() == 24368102


def test_xreload_ref_cycle_dict_1(tpp):
    # Verify that xreload works as expected when there's a reference cycle in
    # the form of a dictionary that contains itself.
    writetext(tpp/"investigation31195273.py", """
        d = {}
        d['x'] = d
        d['f'] = lambda: 10395405
    """)
    from investigation31195273 import d
    f = d['f']
    assert f() == 10395405
    assert d['x'] is d
    writetext(tpp/"investigation31195273.py", """
        d = {}
        d['x'] = d
        d['f'] = lambda: 20963568
    """)
    xreload("investigation31195273")
    assert f() == 20963568
    assert d['x'] is d
    assert d['f'] is f


def test_xreload_ref_other_1(tpp):
    # Verify that xreload works correctly when one class references another
    # livepatched class.
    writetext(tpp/"disappear65532995.py", """
        class A(object):
            def f(self): return 18225731
        class B(object):
            def f(self): return 15723508
        class C(object):
            def f(self): return 19997997
        A.b = B
        A.c = C
        B.a = A
        B.c = C
        C.a = A
        C.b = B
    """)
    from disappear65532995 import A, B, C
    assert A().f() == 18225731
    assert B().f() == 15723508
    assert C().f() == 19997997
    assert A.b is B
    assert A.c is C
    assert B.a is A
    assert B.c is C
    assert C.a is A
    assert C.b is B
    writetext(tpp/"disappear65532995.py", """
        class A(object):
            def f(self): return 23372492
        class B(object):
            def f(self): return 26055354
        class C(object):
            def f(self): return 21904892
        A.b = B
        A.c = C
        B.a = A
        B.c = C
        C.a = A
        C.b = B
    """)
    xreload("disappear65532995")
    assert A().f() == 23372492
    assert B().f() == 26055354
    assert C().f() == 21904892
    assert A.b is B
    assert A.c is C
    assert B.a is A
    assert B.c is C
    assert C.a is A
    assert C.b is B


def test_xreload_metaclass_function_1(tpp):
    # Verify that xreload() works correctly when the metaclass is a custom
    # function.
    writetext(tpp/"weird32312765.py", """
        def my_meta(name, bases, attrs):
            attrs['bar'] = attrs.pop("foo")
            return type(name, bases, attrs)
        class Sport(object, metaclass=my_meta):
            def __init__(self, x):
                self.x = x
            def foo(self, y):
                return self.x + y
    """)

    from weird32312765 import Sport
    a = Sport(34129000)
    assert a.bar(3) == 34129003
    assert not hasattr(a, 'foo')
    writetext(tpp/"weird32312765.py", """
        def my_meta(name, bases, attrs):
            attrs['bar'] = attrs.pop("foo")
            return type(name, bases, attrs)
        class Sport(object, metaclass=my_meta):
            def __init__(self, x):
                self.x = x
            def foo(self, y):
                return self.x + 2*y
    """)
    xreload("weird32312765")
    assert a.bar(3) == 34129006
    assert not hasattr(a, 'foo')


def test_xreload_metaclass_subclass_type_separate_file_1(tpp):
    # Verify that xreload() works correctly when the metaclass is a custom
    # subclass of type, and the metaclass is defined in another file.
    writetext(tpp/"metaclass17670900.py", """
        class MyType(type):
            def __new__(cls, name, bases, attrs):
                attrs['bar'] = attrs.pop("foo")
                return type.__new__(cls, name, bases, attrs)
    """)
    writetext(tpp/"research72020159.py", """
        from metaclass17670900 import MyType
        class Employment(object, metaclass=MyType):
            def __init__(self, x):
                self.x = x
            def foo(self, y):
                return self.x + y
    """)


    from research72020159 import Employment
    a = Employment(97993000)
    assert a.bar(4) == 97993004
    assert not hasattr(a, 'foo')
    writetext(tpp/"research72020159.py", """
        from metaclass17670900 import MyType
        class Employment(object, metaclass=MyType):
            def __init__(self, x):
                self.x = x
            def foo(self, y):
                return self.x + 2*y
    """)

    xreload("research72020159")
    assert a.bar(4) == 97993008
    assert not hasattr(a, 'foo')


def test_xreload_metaclass_subclass_type_same_file_1(tpp):
    # Verify that xreload() works correctly when the metaclass is a custom
    # class of type, and the metaclass is defined in the same file.
    writetext(tpp/"damage28847789.py", """
        class MyType(type):
            def __new__(cls, name, bases, attrs):
                attrs['bar'] = attrs.pop("foo")
                return type.__new__(cls, name, bases, attrs)
        class Agriculture(object, metaclass=MyType):
            def __init__(self, x):
                self.x = x
            def foo(self, y):
                return self.x + y
    """)

    from damage28847789 import Agriculture
    a = Agriculture(72991000)
    assert a.bar(3) == 72991003
    assert not hasattr(a, 'foo')
    writetext(tpp/"damage28847789.py", """
        class MyType(type):
            def __new__(cls, name, bases, attrs):
                attrs['bar'] = attrs.pop("foo")
                return type.__new__(cls, name, bases, attrs)
        class Agriculture(object, metaclass=MyType):
            def __init__(self, x):
                self.x = x
            def foo(self, y):
                return self.x + 2*y
    """)

    xreload("damage28847789")
    assert a.bar(3) == 72991006
    assert not hasattr(a, 'fooxreload_')


def test_xreload_metaclass_changed_1(tpp):
    # Verify that xreload() works correctly when the metaclass definition
    # changed.
    writetext(tpp/"commitee91173998.py", """
        class MyType(type):
            def __new__(cls, name, bases, attrs):
                attrs['technology'] = attrs.pop("procedure")
                return type.__new__(cls, name, bases, attrs)
        class Significance(object, metaclass=MyType):
            def __init__(self, x):
                self.x = x
            def procedure(self, y):
                return self.x + y
    """)

    from commitee91173998 import Significance
    x = Significance(56638000)
    assert x.technology(3) == 56638003
    assert not hasattr(x, 'procedure')
    writetext(tpp/"commitee91173998.py", """
        class MyType(type):
            def __new__(cls, name, bases, attrs):
                attrs['cloud'] = attrs.pop("procedure")
                return type.__new__(cls, name, bases, attrs)
        class Significance(object, metaclass=MyType):
            def __init__(self, x):
                self.x = x
            def procedure(self, y):
                return self.x + 2*y
    """)

    xreload("commitee91173998")
    assert x.cloud(3) == 56638006
    assert not hasattr(x, 'procedure')
    assert not hasattr(x, 'technology')


def test_xreload_object_instance_1(tpp):
    # Verify that object instances are livepatched, for classes defined in the
    # same module.
    writetext(tpp/"fascinating23465210.py", """
        class Framework28105429(object):
            def __init__(self, x):
                self.x = x + 1
        f = Framework28105429(12177800)
    """)
    import fascinating23465210
    from fascinating23465210 import f
    assert f.x == 12177801
    assert fascinating23465210.f is f
    writetext(tpp/"fascinating23465210.py", """
        class Framework28105429(object):
            def __init__(self, x):
                self.x = x + 2
        f = Framework28105429(21904800)
    """)
    xreload("fascinating23465210")
    assert f.x == 21904802
    assert fascinating23465210.f is f


def test_xreload_oldstyle_instance_1(tpp):
    # Verify that old-style instances are livepatched.
    writetext(tpp/"championship63699705.py", """
        class Assembly19457736(object):
            def __init__(self, x):
                self.x = x + 1
        f = Assembly19457736(14184300)
    """)
    import championship63699705
    from championship63699705 import f
    assert f.x == 14184301
    assert championship63699705.f is f
    writetext(tpp/"championship63699705.py", """
        class Assembly19457736(object):
            def __init__(self, x):
                self.x = x + 2
        f = Assembly19457736(23814200)
    """)
    xreload("championship63699705")
    assert f.x == 23814202
    assert championship63699705.f is f


def test_xreload_instance_slots_1(tpp):
    # Verify that instances of classes with __slots__ are livepatched.
    writetext(tpp/"policeman45476673.py", """
        class Research(object):
            __slots__ = ['tactic']
            def __init__(self, t): self.tactic = t
            def weave(self): return 16658900 + self.tactic
        r = Research(5)
    """)
    import policeman45476673 as m
    r = m.r
    Research = m.Research
    assert             r.weave() == 16658905
    assert   Research(5).weave() == 16658905
    assert m.Research(5).weave() == 16658905
    writetext(tpp/"policeman45476673.py", """
        class Research(object):
            __slots__ = ['tactic']
            def __init__(self, t): self.tactic = t
            def weave(self): return 21093700 + self.tactic
        r = Research(7)
    """)
    xreload("policeman45476673")
    assert r is m.r
    assert Research is m.Research
    assert             r.weave() == 21093707
    assert   Research(7).weave() == 21093707
    assert m.Research(7).weave() == 21093707


def test_xreload_instance_slots_changes_1(tpp):
    # Verify that if a class's __slots__ changes, we fallback to not updating
    # methods.
    writetext(tpp/"disaster96211372.py", """
        class Society(object):
            __slots__ = ['timber']
            def __init__(self, t): self.timber = t
            def casino(self): return 16658900 + self.timber
        society = Society(5)
    """)
    import disaster96211372 as m
    society = m.society
    Society = m.Society
    assert      society.casino() == 16658905
    assert    m.society.casino() == 16658905
    assert   Society(9).casino() == 16658909
    assert m.Society(9).casino() == 16658909
    writetext(tpp/"disaster96211372.py", """
        class Society(object):
            __slots__ = ['timber', 'convenience']
            def __init__(self, t): self.timber = t
            def casino(self): return 22957600 + self.timber
        society = Society(7)
    """)
    xreload("disaster96211372")
    assert society is not m.society
    assert Society is not m.Society
    assert      society.casino() == 16658905
    assert    m.society.casino() == 22957607
    assert   Society(9).casino() == 16658909
    assert m.Society(9).casino() == 22957609


def test_xreload_instance_dict_to_slots_1(tpp):
    # Verify that if a class changes from using __dict__ to __slots__, we
    # fallback to not updating instances.
    writetext(tpp/"confidence60441283.py", """
        class Communication(object):
            pass
        c = Communication()
        c.a = 13977754
    """)
    import confidence60441283
    c = confidence60441283.c
    assert confidence60441283.c.a == 13977754
    assert                    c.a == 13977754
    writetext(tpp/"confidence60441283.py", """
        class Communication(object):
            __slots__ = ['a']
        c = Communication()
        c.a = 22746166
    """)
    xreload("confidence60441283")
    assert confidence60441283.c.a == 22746166
    assert                    c.a == 13977754


def test_xreload_instance_slots_to_dict_1(tpp):
    # Verify that if a class changes from using __slots__ to __dict__, we
    # fallback to not updating instances.
    writetext(tpp/"lawmaker77936801.py", """
        class Application(object):
            __slots__ = ['x']
        a = Application()
        a.x = 12966740
    """)
    import lawmaker77936801
    a = lawmaker77936801.a
    assert lawmaker77936801.a.x == 12966740
    assert                  a.x == 12966740
    writetext(tpp/"lawmaker77936801.py", """
        class Application(object):
            pass
        a = Application()
        a.x = 28411441
    """)
    xreload("lawmaker77936801")
    assert lawmaker77936801.a.x == 28411441
    assert                  a.x == 12966740


def test_xreload_class_decorator_mutate_1(tpp):
    # Verify that we successfully livepatch a class even if decorated by a
    # class decorator that mutates its input.
    writetext(tpp/"concrete90418809.py", """
        def conception(cls):
            orig_number = cls.number
            def number(self):
                return orig_number(self) + 1
            cls.number = number
            return cls
        @conception
        class Obvious(object):
            def number(self): return 17010600
    """)
    from concrete90418809 import Obvious
    x = Obvious()
    assert x.number() == 17010601
    writetext(tpp/"concrete90418809.py", """
        def conception(cls):
            orig_number = cls.number
            def number(self):
                return orig_number(self) + 2
            cls.number = number
            return cls
        @conception
        class Obvious(object):
            def number(self): return 24590600
    """)
    xreload("concrete90418809")
    assert x.number() == 24590602


def test_xreload_class_decorator_wrap_1(tpp):
    # Verify that we successfully livepatch a class even if decorated by a
    # class decorator that returns a new class.
    writetext(tpp/"brilliant47487973.py", """
        def bishop(cls):
            class T(cls):
                def life(self):
                    return self.__class__.__base__.life(self) + self.x
            return T
        @bishop
        class Hockey(object):
            def __init__(self, x): self.x = x
            def life(self): return 16463500
    """)
    from brilliant47487973 import Hockey
    x = Hockey(3)
    assert x.life() == 16463503
    writetext(tpp/"brilliant47487973.py", """
        def bishop(cls):
            class T(cls):
                def life(self):
                    return self.__class__.__base__.life(self) + 2*self.x
            return T
        @bishop
        class Hockey(object):
            def __init__(self, x): self.x = x
            def life(self): return 22490400
    """)
    xreload("brilliant47487973")
    assert x.life() == 22490406


def test_xreload_filename_1(tpp):
    # Verify that xreload() can take a fully-qualified filename.
    writetext(tpp/"carrot44854954.py", """
        def solution(): return 12599597
    """)
    from carrot44854954 import solution
    assert solution() == 12599597
    writetext(tpp/"carrot44854954.py", """
        def solution(): return 28989003
    """)
    xreload(str(tpp/"carrot44854954.py"))
    assert solution() == 28989003


def test_xreload_filename_symlink_1(tpp):
    # Verify that xreload() can take a fully-qualified filename that's been
    # symlinked.
    writetext(tpp/"earthquake73307982.py", """
        def improvement(): return 17838028
    """)
    os.symlink("earthquake73307982.py", str(tpp/"laboratory92470174.py"))
    from laboratory92470174 import improvement
    assert improvement() == 17838028
    writetext(tpp/"earthquake73307982.py", """
        def improvement(): return 22857404
    """)
    os.symlink("earthquake73307982.py", str(tpp/"foundation27583240.py"))
    xreload(str(tpp/"foundation27583240.py"))
    assert improvement() == 22857404


def test_xreload_py_suffix_1(tpp):
    # Verify that xreload() can take a relative module name with extraneous
    # ".py" suffix if the module name is unique.
    writetext(tpp/"adventure15354953.py", """
        def veteran(): return 13771028
    """)
    from adventure15354953 import veteran
    assert veteran() == 13771028
    writetext(tpp/"adventure15354953.py", """
        def veteran(): return 22452354
    """)
    xreload("adventure15354953.py")
    assert veteran() == 22452354


def test_xreload_relative_module_py_suffix_1(tpp):
    # Verify that xreload() can take a relative module name that's inside a
    # package.
    os.mkdir(str(tpp/"grass42042608"))
    writetext(tpp/"grass42042608/__init__.py", "")
    writetext(tpp/"grass42042608/familiar93153179.py", """
        def triumph(): return 16758056
    """)
    from grass42042608.familiar93153179 import triumph
    assert triumph() == 16758056
    writetext(tpp/"grass42042608/familiar93153179.py", """
        def triumph(): return 25006012
    """)
    xreload("familiar93153179.py")
    assert triumph() == 25006012


def test_xreload_non_unique_name_1(tpp):
    # Verify that if we give a non-unique name, we get an UnknownModuleError.
    os.mkdir(str(tpp/"bubble28897057"))
    os.mkdir(str(tpp/"bubble28897057/d1"))
    os.mkdir(str(tpp/"bubble28897057/d2"))
    writetext(tpp/"bubble28897057/__init__.py", "")
    writetext(tpp/"bubble28897057/d1/__init__.py", "")
    writetext(tpp/"bubble28897057/d2/__init__.py", "")
    writetext(tpp/"bubble28897057/d1/departure65970807.py", """
        def happiness(): return 15361786
    """)
    writetext(tpp/"bubble28897057/d2/departure65970807.py", """
        def happiness(): return 23999960
    """)
    from bubble28897057.d1.departure65970807 import happiness as h1
    from bubble28897057.d2.departure65970807 import happiness as h2
    assert h1() == 15361786
    assert h2() == 23999960
    with pytest.raises(UnknownModuleError):
        xreload("departure65970807.py")
    from bubble28897057.d1.departure65970807 import happiness as h1b
    from bubble28897057.d2.departure65970807 import happiness as h2b
    assert h1 is h1b
    assert h2 is h2b
    assert h1() == 15361786
    assert h2() == 23999960


def test_xreload_unknown_name_1(tpp):
    # Verify that if we give an unknown module name or filename, we get an
    # UnknownModuleError.
    with pytest.raises(UnknownModuleError):
        xreload("marketplace81346285")
    with pytest.raises(UnknownModuleError):
        xreload("marketplace81346285.py")
    with pytest.raises(UnknownModuleError):
        xreload(str(tpp/"marketplace81346285.py"))
    with pytest.raises(UnknownModuleError):
        xreload("./marketplace81346285.py")
    with pytest.raises(UnknownModuleError):
        xreload("/marketplace81346285.py")


def test_xreload_dynamic_class_same_name_1(tpp):
    # Verify that if a class is dynamically constructed multiple times with
    # the same __name__, that doesn't confuse us.  We rely on the name
    # pointing to a class, not the class's own idea of name.
    writetext(tpp/"discourse67226455.py", """
        def make_lesson(n):
            class Lesson(object):
                def instinct(self): return self.n + 1
            Lesson.n = n
            return Lesson
        Lesson5 = make_lesson(51054900)
        Lesson6 = make_lesson(61024300)
    """)
    from discourse67226455 import Lesson5, Lesson6
    x5 = Lesson5()
    x6 = Lesson6()
    assert x5.instinct() == 51054901
    assert x6.instinct() == 61024301
    writetext(tpp/"discourse67226455.py", """
        def make_lesson(n):
            class Lesson(object):
                def instinct(self): return self.n + 2
            Lesson.n = n
            return Lesson
        Lesson5 = make_lesson(52043900)
        Lesson6 = make_lesson(62092500)
    """)
    xreload("discourse67226455")
    assert x5.instinct() == 52043902
    assert x6.instinct() == 62092502



# XXX __livepatch__ in object
# XXX caching: check (using a hook) that we only get called once per object
# XXX __livepatch__ on class.
# XXX change in staticmethod/classmethod/method - what should that do?
