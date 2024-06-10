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
"""Tests for slice transformation."""

import itertools

from absl.testing import absltest
from absl.testing import parameterized
from grain._src.python.lazy_dataset import lazy_dataset
import grain._src.python.lazy_dataset.transformations.slice as slice_ds
from typing_extensions import override


class EmptyLazyMapDataset(lazy_dataset.LazyMapDataset[int]):

  def __init__(self):
    super().__init__(parents=[])

  @override
  def __len__(self) -> int:
    return 0

  @override
  def __getitem__(self, index):
    raise IndexError("Index out of range")


class SliceLazyMapDatasetTest(parameterized.TestCase):

  @parameterized.parameters(
      (0, 1, 20),
      (0, 2, 10),
      (1, 2, 10),
      (0, 3, 7),
      (1, 3, 7),
      (2, 3, 6),
      (30, 100, 0),
  )
  def test_len(self, start: int, step: int, expected_len: int):
    ds = lazy_dataset.RangeLazyMapDataset(20)
    sl = slice(start, 20, step)
    range_ds_for_process = slice_ds.SliceLazyMapDataset(ds, sl)
    self.assertLen(range_ds_for_process, expected_len)

  @parameterized.parameters(
      itertools.product(range(-8, 8), range(-9, 8), [-2, -1, 1, 2])
  )
  def test_getitem(self, start: int, stop: int, step: int):
    ds = lazy_dataset.RangeLazyMapDataset(20)
    ds = slice_ds.SliceLazyMapDataset(ds, slice(start, stop, step))
    ds_items = [ds[i] for i in range(len(ds))]
    self.assertSequenceEqual(ds_items, list(range(20))[start:stop:step])

  @parameterized.parameters(
      itertools.product(range(-8, 8), range(-9, 8), [-2, -1, 1, 2])
  )
  def test_getitem_sice(self, start: int, stop: int, step: int):
    ds = lazy_dataset.RangeLazyMapDataset(20)
    ds = ds[start:stop:step]
    ds_items = [ds[i] for i in range(len(ds))]
    self.assertSequenceEqual(ds_items, list(range(20))[start:stop:step])

  @parameterized.parameters(
      itertools.product(range(-8, 8), range(-9, 8), [-2, -1, 1, 2])
  )
  def test_iter(self, start: int, stop: int, step: int):
    ds = lazy_dataset.RangeLazyMapDataset(20)
    ds = slice_ds.SliceLazyMapDataset(ds, slice(start, stop, step))
    ds_iter = iter(ds)
    ds_items = list(ds_iter)
    self.assertSequenceEqual(ds_items, list(range(20))[start:stop:step])

  def test_slice_of_empty_dataset_is_empty(self):
    ds = EmptyLazyMapDataset()
    ds = slice_ds.SliceLazyMapDataset(ds, slice(0, 10))
    self.assertEmpty(ds)


if __name__ == "__main__":
  absltest.main()
