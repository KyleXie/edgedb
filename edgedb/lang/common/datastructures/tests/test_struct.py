##
# Copyright (c) 2011 MagicStack Inc.
# All rights reserved.
#
# See LICENSE for details.
##

import pickle

from edgedb.lang.common.datastructures.struct import Struct, MixedStruct, Field
from edgedb.lang.common.debug import assert_raises


class PickleTest(Struct):
    a = Field(str, default='42')
    b = Field(int)


class PickleTestMixed(MixedStruct):
    a = Field(str, default='42')
    b = Field(int)


class TestUtilsDSStruct:
    def test_utils_ds_struct_basics(self):
        class Test(Struct):
            field1 = Field(type=str, default='42')
            field2 = Field(type=bool)

        with assert_raises(TypeError, error_re='field2 is required'):
            Test()

        t = Test(field2=False)
        assert t.field1 == '42'
        assert t.field2 is False

        assert set(t) == {'field1', 'field2'}

    def test_utils_ds_struct_coercion(self):
        class Test(Struct):
            field = Field(type=int, coerce=True)

        assert Test(field=1).field == 1
        assert Test(field='42').field == 42
        with assert_raises(TypeError, error_re='auto-coercion'):
            Test(field='42.2')

        class Test(Struct):
            field = Field(type=int)

        assert Test(field=1).field == 1
        with assert_raises(TypeError, error_re='expected int'):
            Test(field='42')

    def test_utils_ds_struct_strictness(self):
        class Test(Struct):
            field = Field(str, None)

        assert Test.__slots__ == ('field', )

        t = Test()
        t.field = 'foo'
        assert t.field == 'foo'
        with assert_raises(AttributeError, error_re='has no attribute'):
            t.foo = 'bar'

        class DTest(Test):
            field2 = Field(int, None)

        t = DTest()
        t.field = '1'
        t.field2 = 2
        assert t.field == '1'
        assert t.field2 == 2
        with assert_raises(AttributeError, error_re='has no attribute'):
            t.foo = 'bar'

        with assert_raises(
                TypeError, error_re='field3 is an invalid argument'):
            DTest(field='1', field2=2, field3='aaa')

        t = DTest()

        with assert_raises(
                TypeError, error_re='field3 is an invalid argument'):
            t.update(field='1', field2=2, field3='aaa')

    def test_utils_ds_struct_mixed(self):
        class Test(MixedStruct):
            field1 = Field(type=str, default='42')
            field2 = Field(type=bool)

        t1 = Test(field1='field1', field2=True, spam='ham')
        t1.update(ham='spam')

        t1.monty = 'python'
        assert t1.monty == 'python'

    def test_utils_ds_struct_pickle(self):
        s1 = PickleTest(b=41)
        s2 = pickle.loads(pickle.dumps(s1))
        assert s2.b == 41 and s2.a == '42'
        assert s2.__class__.__name__ == 'PickleTest'

        s1 = PickleTestMixed(b=41)
        s2 = pickle.loads(pickle.dumps(s1))
        assert s2.b == 41 and s2.a == '42'
        assert s2.__class__.__name__ == 'PickleTestMixed'
