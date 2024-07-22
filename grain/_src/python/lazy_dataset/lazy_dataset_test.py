# Copyright 2023 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for LazyDataset."""

import dataclasses
import sys
from typing import TypeVar, overload

from absl.testing import absltest
from absl.testing import parameterized
from grain._src.core import transforms
import multiprocessing as mp
from grain._src.python import options
from grain._src.python.lazy_dataset import base
from grain._src.python.lazy_dataset import lazy_dataset
import numpy as np
from typing_extensions import override


_T = TypeVar('_T')


@dataclasses.dataclass(frozen=True)
class FilterKeepingOddElementsOnly(transforms.FilterTransform):

  def filter(self, element: int) -> bool:
    return bool(element % 2)


@dataclasses.dataclass(frozen=True)
class RandomMapAddingRandomInt(transforms.RandomMapTransform):

  def random_map(self, element: int, rng: np.random.Generator) -> int:
    return element + rng.integers(0, 100)


@dataclasses.dataclass(frozen=True)
class RandomMapAlwaysAddingOne(transforms.RandomMapTransform):

  def random_map(self, element: int, rng: np.random.Generator) -> int:
    return element + 1


@dataclasses.dataclass(frozen=True)
class MapTransformAddingOne(transforms.MapTransform):

  def map(self, element: int) -> int:
    return element + 1


@dataclasses.dataclass(frozen=True)
class MapWithIndexProducingIndexElementTuple(transforms.MapWithIndexTransform):

  def map_with_index(self, index: int, element: int) -> tuple[int, int]:
    return (index, element)


class RangeLazyMapDatasetTest(absltest.TestCase):

  def test_len(self):
    ds = lazy_dataset.RangeLazyMapDataset(12)
    self.assertLen(ds, 12)
    ds = lazy_dataset.RangeLazyMapDataset(0, 12)
    self.assertLen(ds, 12)
    ds = lazy_dataset.RangeLazyMapDataset(2, 12)
    self.assertLen(ds, 10)
    ds = lazy_dataset.RangeLazyMapDataset(2, 12, 1)
    self.assertLen(ds, 10)
    ds = lazy_dataset.RangeLazyMapDataset(2, 12, 2)
    self.assertLen(ds, 5)
    ds = lazy_dataset.RangeLazyMapDataset(2, 13, 2)
    self.assertLen(ds, 6)

  def test_getitem(self):
    ds = lazy_dataset.RangeLazyMapDataset(12)
    for i in range(12):
      self.assertEqual(ds[i], i)
    for i in range(12):
      self.assertEqual(ds[i + 12], i)
    ds = lazy_dataset.RangeLazyMapDataset(2, 9, 2)
    self.assertEqual(ds[0], 2)
    self.assertEqual(ds[1], 4)
    self.assertEqual(ds[2], 6)
    self.assertEqual(ds[3], 8)
    self.assertEqual(ds[4], 2)
    self.assertEqual(ds[5], 4)

  def test_iter(self):
    ds = lazy_dataset.RangeLazyMapDataset(12)
    ds_iter = iter(ds)
    elements = [next(ds_iter) for _ in range(12)]
    self.assertEqual(elements, list(range(12)))
    ds = lazy_dataset.RangeLazyMapDataset(2, 9, 2)
    ds_iter = iter(ds)
    elements = [next(ds_iter) for _ in range(4)]
    self.assertEqual(elements, [2, 4, 6, 8])


class Source15IntsFrom0:

  def __init__(self):
    pass

  def __len__(self) -> int:
    return 15

  def __getitem__(self, index):
    return index


class InverseUniformSelectionMap(base.DatasetSelectionMap):

  def __len__(self):
    return 10

  def __getitem__(self, index):
    return (index + 1) % 2, index // 2


class Source15IntsFrom0LazyMapDataset(lazy_dataset.LazyMapDataset[int]):

  def __init__(self):
    super().__init__(parents=[])

  @override
  def __len__(self) -> int:
    return 15

  @overload
  def __getitem__(self, index: slice) -> lazy_dataset.LazyMapDataset[int]:
    ...

  @overload
  def __getitem__(self, index: int) -> int:
    ...

  @override
  def __getitem__(self, index):
    if isinstance(index, slice):
      return self.slice(index)
    return index % len(self)


class Source15IntsFrom0LazyIterDataset(lazy_dataset.LazyIterDataset[int]):

  def __init__(self):
    super().__init__(parents=[])

  @override
  def __iter__(self):
    return iter(range(15))


class IdentityLazyMapDataset(lazy_dataset.LazyMapDataset[_T]):

  def __init__(self, parent: lazy_dataset.LazyMapDataset[_T]):
    super().__init__(parents=parent)

  @override
  def __len__(self) -> int:
    return len(self._parent)

  @override
  def __getitem__(self, index):
    return self._parent[index]


class LazyDatasetTest(parameterized.TestCase):

  def test_parents_source_dataset_has_no_parents(self):
    ds = Source15IntsFrom0LazyMapDataset()
    self.assertEmpty(ds.parents)

  def test_parents_single_source_dataset_has_one_parent(self):
    source_ds = Source15IntsFrom0LazyMapDataset()
    ds = IdentityLazyMapDataset(source_ds)
    self.assertLen(ds.parents, 1)
    self.assertEqual(ds.parents[0], source_ds)

  def test_source(self):
    ds = lazy_dataset.LazyMapDataset.source(Source15IntsFrom0())
    self.assertIsInstance(ds, lazy_dataset.LazyMapDataset)
    self.assertLen(ds, 15)
    self.assertEqual(list(ds), list(range(15)))

  @parameterized.parameters(
      # pyformat: disable
      dict(proportions=None,
           expected=[
               0, 100, 1, 101, 2, 102, 3, 103, 4, 104, 5, 105, 6, 106, 7, 107,
               8, 108, 9, 109, 10, 110, 11, 111, 12, 112, 13, 113, 14, 114]),
      dict(proportions=[1, 2],
           expected=[
               0, 100, 101, 1, 102, 103, 2, 104, 105, 3, 106, 107, 4, 108, 109,
               5, 110, 111, 6, 112, 113, 7]),
      # pyformat: enable
  )
  def test_mix(self, proportions, expected):
    datasets = [
        Source15IntsFrom0LazyMapDataset(),
        Source15IntsFrom0LazyMapDataset().map(lambda x: x + 100),
    ]
    ds = lazy_dataset.LazyMapDataset.mix(datasets, proportions)
    self.assertIsInstance(ds, lazy_dataset.LazyMapDataset)
    self.assertLen(ds, len(expected))
    self.assertEqual(list(ds), expected)

  def test_select_from_datasets(self):
    datasets = [
        Source15IntsFrom0LazyMapDataset(),
        Source15IntsFrom0LazyMapDataset().map(lambda x: x + 100),
    ]
    selection_map = InverseUniformSelectionMap()
    ds = lazy_dataset.LazyMapDataset.select_from_datasets(
        datasets, selection_map
    )
    self.assertIsInstance(ds, lazy_dataset.LazyMapDataset)
    self.assertLen(ds, 10)
    self.assertEqual(list(ds), [100, 0, 101, 1, 102, 2, 103, 3, 104, 4])

  @parameterized.parameters(
      dict(initial_ds=Source15IntsFrom0LazyMapDataset()),
      dict(initial_ds=Source15IntsFrom0LazyIterDataset()),
  )
  def test_batch(self, initial_ds):
    ds = initial_ds.batch(batch_size=3)
    if isinstance(ds, lazy_dataset.LazyMapDataset):
      self.assertLen(ds, 5)
    np.testing.assert_equal(
        list(ds),
        [
            np.array([0, 1, 2]),
            np.array([3, 4, 5]),
            np.array([6, 7, 8]),
            np.array([9, 10, 11]),
            np.array([12, 13, 14]),
        ],
    )

  @parameterized.parameters(
      dict(initial_ds=Source15IntsFrom0LazyMapDataset()),
      dict(initial_ds=Source15IntsFrom0LazyIterDataset()),
  )
  def test_batch_with_drop_remainder(self, initial_ds):
    ds = initial_ds.batch(batch_size=6, drop_remainder=True)
    if isinstance(ds, lazy_dataset.LazyMapDataset):
      self.assertLen(ds, 2)
    np.testing.assert_equal(
        list(ds),
        [
            np.array([0, 1, 2, 3, 4, 5]),
            np.array([6, 7, 8, 9, 10, 11]),
        ],
    )

  @parameterized.parameters(
      dict(initial_ds=Source15IntsFrom0LazyMapDataset()),
      dict(initial_ds=Source15IntsFrom0LazyIterDataset()),
  )
  def test_batch_with_batch_fn(self, initial_ds):
    ds = initial_ds.batch(
        batch_size=4,
        batch_fn=lambda xs: np.expand_dims(np.array(xs), axis=0),
    )
    if isinstance(ds, lazy_dataset.LazyMapDataset):
      self.assertLen(ds, 4)
    np.testing.assert_equal(
        list(ds),
        [
            np.array([[0, 1, 2, 3]]),
            np.array([[4, 5, 6, 7]]),
            np.array([[8, 9, 10, 11]]),
            np.array([[12, 13, 14]]),
        ],
    )

  @parameterized.parameters(
      dict(initial_ds=Source15IntsFrom0LazyMapDataset()),
      dict(initial_ds=Source15IntsFrom0LazyIterDataset()),
  )
  def test_filter_with_callable(self, initial_ds):
    ds = initial_ds.filter(lambda x: x % 2 == 0)
    self.assertSequenceEqual(list(iter(ds)), [0, 2, 4, 6, 8, 10, 12, 14])

  @parameterized.parameters(
      dict(initial_ds=Source15IntsFrom0LazyMapDataset()),
      dict(initial_ds=Source15IntsFrom0LazyIterDataset()),
  )
  def test_filter_with_transform(self, initial_ds):
    ds = initial_ds.filter(FilterKeepingOddElementsOnly())
    self.assertSequenceEqual(list(iter(ds)), [1, 3, 5, 7, 9, 11, 13])

  @parameterized.parameters(
      dict(initial_ds=Source15IntsFrom0LazyMapDataset()),
      dict(initial_ds=Source15IntsFrom0LazyIterDataset()),
  )
  def test_filter_with_callable_and_transform_combined(self, initial_ds):
    ds = initial_ds.filter(lambda x: 3 < x < 10).filter(
        FilterKeepingOddElementsOnly()
    )
    self.assertSequenceEqual(list(iter(ds)), [5, 7, 9])

  @parameterized.parameters(
      dict(initial_ds=Source15IntsFrom0LazyMapDataset()),
      dict(initial_ds=Source15IntsFrom0LazyIterDataset()),
  )
  def test_filter_has_one_parent(self, initial_ds):
    ds = initial_ds.filter(lambda x: True)
    self.assertLen(ds.parents, 1)

  def test_filter_subscription_returns_correct_elements(self):
    ds = Source15IntsFrom0LazyMapDataset().filter(lambda x: x % 2 == 0)
    self.assertSequenceEqual(list(iter(ds)), [0, 2, 4, 6, 8, 10, 12, 14])
    self.assertEqual(ds[0], 0)
    self.assertEqual(ds[12], 12)
    self.assertEqual(ds[8], 8)
    self.assertIsNone(ds[3])
    self.assertIsNone(ds[5])
    self.assertIsNone(ds[13])

  @parameterized.parameters(
      (0),
      (9),
      (30),
  )
  def test_filter_does_not_affect_len(self, ds_length):
    ds = lazy_dataset.RangeLazyMapDataset(ds_length)
    self.assertLen(ds, ds_length)
    ds = ds.filter(lambda x: x % 2 == 0)
    self.assertLen(ds, ds_length)

  @parameterized.named_parameters(
      dict(
          testcase_name='default_args',
          read_options=None,
          allow_nones=False,
          expected=[0, 2, 4, 6, 8, 10, 12, 14],
      ),
      dict(
          testcase_name='custom_read_options',
          read_options=options.ReadOptions(
              num_threads=1, prefetch_buffer_size=1
          ),
          allow_nones=False,
          expected=[0, 2, 4, 6, 8, 10, 12, 14],
      ),
      dict(
          testcase_name='allow_nones',
          read_options=None,
          allow_nones=True,
          expected=[
              0,
              None,
              2,
              None,
              4,
              None,
              6,
              None,
              8,
              None,
              10,
              None,
              12,
              None,
              14,
          ],
      ),
  )
  def test_to_iter_dataset(self, read_options, allow_nones, expected):
    ds = (
        Source15IntsFrom0LazyMapDataset()
        .filter(lambda x: x % 2 == 0)
        .to_iter_dataset(read_options=read_options, allow_nones=allow_nones)
    )
    self.assertSequenceEqual(list(iter(ds)), expected)

  def test_slice_with_just_stop_returns_correct_elements(self):
    ds = Source15IntsFrom0LazyMapDataset().slice(slice(7))
    self.assertSequenceEqual(list(iter(ds)), [0, 1, 2, 3, 4, 5, 6])

  def test_slice_with_start_and_stop_returns_correct_elements(self):
    ds = Source15IntsFrom0LazyMapDataset().slice(slice(3, 9))
    self.assertSequenceEqual(list(iter(ds)), [3, 4, 5, 6, 7, 8])

  def test_slice_with_start_stop_and_step_returns_correct_elements(self):
    ds = Source15IntsFrom0LazyMapDataset().slice(slice(2, 11, 3))
    self.assertSequenceEqual(list(iter(ds)), [2, 5, 8])

  def test_slice_composition_returns_correct_elements(self):
    ds = (
        Source15IntsFrom0LazyMapDataset()
        .slice(slice(1, 10, 2))  # 1, 3, 5, 7, 9
        .slice(slice(1, 3))  # 3, 5
    )
    self.assertSequenceEqual(list(iter(ds)), [3, 5])

  def test_slice_and_filter_composed_returns_correct_elements(self):
    ds = (
        Source15IntsFrom0LazyMapDataset()
        .slice(slice(1, 10, 2))  # 1, 3, 5, 7, 9
        .filter(lambda x: x % 3 == 0 or x == 7)  # None, 3, None, 7, 9
        .filter(lambda x: x > 5)  # None, None, None, 7, 9
        .slice(slice(2, 4))  # None, 7
    )
    self.assertSequenceEqual(list(iter(ds)), [7])

  def test_repeat_updates_length(self):
    ds = Source15IntsFrom0LazyMapDataset().repeat(3)
    self.assertLen(ds, 45)

  def test_repeat_with_none_epochs_updates_length_to_maxsize(self):
    ds = Source15IntsFrom0LazyMapDataset().repeat(num_epochs=None)
    self.assertLen(ds, sys.maxsize)

  def test_repeat_produces_additional_elements_when_iterated(self):
    ds = Source15IntsFrom0LazyMapDataset()[:5].repeat(2)
    self.assertSequenceEqual(list(ds), [0, 1, 2, 3, 4, 0, 1, 2, 3, 4])

  def test_slice_filter_repeat_composed_returns_correct_elements(self):
    ds = (
        Source15IntsFrom0LazyMapDataset()
        .slice(slice(1, 10, 2))  # 1, 3, 5, 7, 9
        .filter(lambda x: x < 6)  # 1, 3, 5, None, None
        .repeat(2)
    )
    self.assertSequenceEqual(list(ds), [1, 3, 5, 1, 3, 5])

  def test_shuffle_does_not_affect_len(self):
    ds = Source15IntsFrom0LazyMapDataset().shuffle(seed=123)
    self.assertLen(ds, 15)

  def test_shuffle_does_not_affect_elements(self):
    ds = Source15IntsFrom0LazyMapDataset()
    elements_before_shuffle = list(ds)
    ds = ds.shuffle(seed=123)
    self.assertSameElements(list(ds), elements_before_shuffle)

  def test_shuffle_with_same_seed_returns_same_elements(self):
    ds1 = Source15IntsFrom0LazyMapDataset().shuffle(seed=123)
    ds2 = Source15IntsFrom0LazyMapDataset().shuffle(seed=123)
    self.assertSequenceEqual(list(ds1), list(ds2))

  # While it's possible for two orders to be the same, it's very unlikely
  # (1 / 15!) so we don't bother mocking the random number generator.
  def test_shuffle_with_different_seed_returns_different_elements(self):
    ds1 = Source15IntsFrom0LazyMapDataset().shuffle(seed=123)
    ds2 = Source15IntsFrom0LazyMapDataset().shuffle(seed=456)
    self.assertNotEqual(list(ds1), list(ds2))

  def test_shuffle_uses_different_order_for_different_epochs(self):
    ds = Source15IntsFrom0LazyMapDataset().shuffle(seed=123)
    epoch_1 = [ds[i] for i in range(15)]
    epoch_2 = [ds[i] for i in range(15, 30)]
    self.assertSameElements(epoch_1, epoch_2)
    self.assertNotEqual(epoch_1, epoch_2)

  def test_multiprocess_prefetch(self):
    ds = (
        Source15IntsFrom0LazyMapDataset()
        .to_iter_dataset()
        .prefetch(options.MultiprocessingOptions(num_workers=4))
    )
    self.assertSequenceEqual(list(ds), list(range(15)))

  @parameterized.parameters(
      dict(initial_ds=Source15IntsFrom0LazyMapDataset()),
      dict(initial_ds=Source15IntsFrom0LazyIterDataset()),
  )
  def test_random_map_has_one_parent(self, initial_ds):
    ds = initial_ds.random_map(lambda x, rng: 2 * x, seed=123)
    self.assertLen(ds.parents, 1)

  def test_random_map_does_not_affect_len(self):
    ds = Source15IntsFrom0LazyMapDataset().random_map(
        lambda x, rng: True, seed=123
    )
    self.assertLen(ds, 15)

  @parameterized.product(
      initial_ds=[
          Source15IntsFrom0LazyMapDataset(),
          Source15IntsFrom0LazyIterDataset(),
      ],
      transform=[RandomMapAlwaysAddingOne(), lambda x, rng: x + 1],
  )
  def test_random_map_produces_correct_elements(self, initial_ds, transform):
    ds = initial_ds.random_map(transform, seed=123)
    self.assertSequenceEqual(
        list(ds), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
    )

  @parameterized.product(
      seed=[0, 123, 893247023984],
      initial_ds=[
          Source15IntsFrom0LazyMapDataset(),
          Source15IntsFrom0LazyIterDataset(),
      ],
  )
  def test_random_map_is_deterministic(self, seed, initial_ds):
    ds = initial_ds.random_map(RandomMapAddingRandomInt(), seed=seed)
    items_1 = list(ds)
    items_2 = list(ds)
    self.assertEqual(items_1, items_2)

  @parameterized.parameters(
      dict(initial_ds=Source15IntsFrom0LazyMapDataset()),
      dict(initial_ds=Source15IntsFrom0LazyIterDataset()),
  )
  def test_random_map_returns_different_results_for_different_seeds(
      self, initial_ds
  ):
    ds1 = initial_ds.random_map(RandomMapAddingRandomInt(), seed=123)
    ds2 = initial_ds.random_map(RandomMapAddingRandomInt(), seed=456)
    self.assertNotEqual(list(ds1), list(ds2))

  def test_map_does_not_affect_len(self):
    ds = Source15IntsFrom0LazyMapDataset().map(lambda x: x + 1)
    self.assertLen(ds, 15)

  @parameterized.parameters(
      dict(initial_ds=Source15IntsFrom0LazyMapDataset()),
      dict(initial_ds=Source15IntsFrom0LazyIterDataset()),
  )
  def test_map_has_one_parent(self, initial_ds):
    ds = initial_ds.map(lambda x: x)
    self.assertLen(ds.parents, 1)

  @parameterized.product(
      initial_ds=[
          Source15IntsFrom0LazyMapDataset(),
          Source15IntsFrom0LazyIterDataset(),
      ],
      transform=[MapTransformAddingOne(), lambda x: x + 1],
  )
  def test_map_produces_correct_elements(self, initial_ds, transform):
    ds = initial_ds.map(transform)
    self.assertSequenceEqual(
        list(ds), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
    )

  def test_map_with_index_does_not_affect_len(self):
    ds = Source15IntsFrom0LazyMapDataset().map_with_index(lambda i, x: x + i)
    self.assertLen(ds, 15)

  def test_map_with_index_has_one_parent(self):
    ds = Source15IntsFrom0LazyMapDataset().map_with_index(lambda i, x: x)
    self.assertLen(ds.parents, 1)

  @parameterized.parameters(
      (MapWithIndexProducingIndexElementTuple(),), ((lambda i, x: (i, x)),)
  )
  def test_map_with_index_produces_correct_elements(self, transform):
    ds = Source15IntsFrom0LazyMapDataset()[:5]  # [0, 1, 2, 3, 4]
    ds = ds.map(lambda x: 2 * x)  # [0, 2, 4, 6, 8]
    ds = ds.map_with_index(transform)
    self.assertSequenceEqual(list(ds), [(0, 0), (1, 2), (2, 4), (3, 6), (4, 8)])

  def test_many_operations_chained_together_produce_correct_elements(self):
    # We don't use lambdas for these to keep the information about the type.
    def add_one(x: int) -> int:
      return x + 1

    def add(x: int, y: int) -> int:
      return x + y

    ds = Source15IntsFrom0LazyMapDataset()
    ds = ds[:5]  # [0, 1, 2, 3, 4]
    ds = ds.filter(lambda x: x % 2 == 0)  # [0, None, 2, None, 4]
    ds = ds.map(add_one)  # [1, None, 3, None, 5]
    ds = ds.slice(slice(2, 5))  # [3, None, 5]
    ds = ds.repeat(3)  # [3, None, 5, 3, None, 5, 3, None, 5]
    ds = ds.map_with_index(add)  # [3, None, 7, 6, None, 10, 9, None, 13]
    ds = ds.to_iter_dataset()  # [3, 7, 6, 10, 9, 13]
    ds = ds.filter(lambda x: x % 3 != 0)  # [7, 10, 13]
    ds = ds.map(add_one)  # [8, 11, 14]
    # Note that the final dataset still has the correct type ineferred.
    self.assertSequenceEqual(list(ds), [8, 11, 14])


if __name__ == '__main__':
  absltest.main()
