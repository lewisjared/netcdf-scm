import datetime
import re
import warnings
from unittest.mock import patch

import cf_units
import dask.array as da
import iris
import numpy as np
import pytest

from netcdf_scm.utils import (
    _assert_only_cube_dim_coord_is_time,
    apply_mask,
    assert_all_time_axes_same,
    broadcast_onto_lat_lon_grid,
    get_cube_timeseries_data,
    get_scm_cube_time_axis_in_calendar,
    take_lat_lon_mean,
    unify_lat_lon,
)


def test_assert_only_cube_dim_coord_is_time(test_generic_tas_cube):
    original_cube = test_generic_tas_cube.cube

    error_msg = re.escape("Should only have time coordinate here")

    with pytest.raises(AssertionError, match=error_msg):
        _assert_only_cube_dim_coord_is_time(test_generic_tas_cube)

    # can safely ignore these warnings here
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", ".*Collapsing spatial coordinate 'latitude' without weighting.*"
        )
        test_generic_tas_cube.cube = original_cube.collapsed(
            ["latitude", "time"], iris.analysis.MEAN
        )

    with pytest.raises(AssertionError, match=error_msg):
        _assert_only_cube_dim_coord_is_time(test_generic_tas_cube)

    # can safely ignore these warnings here
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", ".*Using DEFAULT_SPHERICAL.*")
        test_generic_tas_cube.cube = original_cube.collapsed(
            ["latitude", "longitude"],
            iris.analysis.MEAN,
            weights=iris.analysis.cartography.area_weights(original_cube),
        )

    _assert_only_cube_dim_coord_is_time(test_generic_tas_cube)


@patch("netcdf_scm.utils._assert_only_cube_dim_coord_is_time")
def test_get_cube_timeseries_data(mock_assert_only_time, test_generic_tas_cube):
    expected = test_generic_tas_cube.cube.data
    result = get_cube_timeseries_data(test_generic_tas_cube)

    np.testing.assert_array_equal(result, expected)
    mock_assert_only_time.assert_called_with(test_generic_tas_cube)


@pytest.mark.parametrize("out_calendar", ["gregorian", "julian", "365_day"])
def test_get_cube_time_axis_in_calendar(test_generic_tas_cube, out_calendar):
    tcn = test_generic_tas_cube.cube.coord_dims("time")[0]
    ttime = test_generic_tas_cube.cube.dim_coords[tcn]
    expected = cf_units.num2date(ttime.points, ttime.units.name, out_calendar)

    result = get_scm_cube_time_axis_in_calendar(test_generic_tas_cube, out_calendar)
    np.testing.assert_array_equal(result, expected)


def test_assert_all_time_axes_same(test_generic_tas_cube):
    tcn = test_generic_tas_cube.cube.coord_dims("time")[0]
    ttime = test_generic_tas_cube.cube.dim_coords[tcn]
    ttime_axis = cf_units.num2date(ttime.points, ttime.units.name, "gregorian")

    assert_all_time_axes_same([ttime_axis, ttime_axis])

    otime_axis = ttime_axis - datetime.timedelta(10)

    error_msg = re.escape("all the time axes should be the same")
    with pytest.raises(AssertionError, match=error_msg):
        assert_all_time_axes_same([otime_axis, ttime_axis])


def test_take_lat_lon_mean(test_generic_tas_cube):
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", ".*Using DEFAULT_SPHERICAL.*")
        tweights = iris.analysis.cartography.area_weights(test_generic_tas_cube.cube)

    assert len(test_generic_tas_cube.cube.dim_coords) == 3

    result = take_lat_lon_mean(test_generic_tas_cube, tweights)

    assert len(result.cube.dim_coords) == 1
    assert result.cube.cell_methods[0].method == "mean"
    assert result.cube.cell_methods[0].coord_names == ("time",)


@pytest.mark.parametrize("lazy", [True, False])
def test_apply_mask(test_generic_tas_cube, lazy):
    tmask = np.full(test_generic_tas_cube.cube.shape, True)

    assert test_generic_tas_cube.cube.has_lazy_data()
    if not lazy:
        np.testing.assert_equal(test_generic_tas_cube.cube.data.mask, ~tmask)

    result = apply_mask(test_generic_tas_cube, tmask)
    if lazy:
        assert result.cube.has_lazy_data()
    else:
        assert not result.cube.has_lazy_data()
    np.testing.assert_equal(result.cube.data.mask, tmask)


@pytest.mark.parametrize(
    "ttol",
    [0.1, 10 ** -3, 1.5 * 10 ** -5, 10 ** -5, 0.9 * 10 ** -5, 10 ** -10, "default"],
)
def test_unify_lat_lon(test_generic_tas_cube, ttol):
    def get_starting_list(scale):
        base_cube = test_generic_tas_cube.cube.copy()
        other_cube = base_cube.copy()
        other_cube.coords("longitude")[0].points = (
            scale * other_cube.coords("longitude")[0].points
        )
        other_cube.coords("latitude")[0].points = (
            scale * other_cube.coords("latitude")[0].points
        )

        assert (
            other_cube.coords("longitude")[0].points
            == scale * base_cube.coords("longitude")[0].points
        ).all()
        assert (
            other_cube.coords("latitude")[0].points
            == scale * base_cube.coords("latitude")[0].points
        ).all()

        return iris.cube.CubeList([base_cube, other_cube])

    default = False if ttol != "default" else True
    ttol = ttol if ttol != "default" else 10 ** -6
    for loop_ttol in [ttol * 0.1, ttol * 10 ** -5]:
        tlist = get_starting_list(scale=1 + loop_ttol)
        if default:
            unify_lat_lon(tlist)
        else:
            unify_lat_lon(tlist, rtol=ttol)

        assert (
            tlist[0].coords("longitude")[0].points
            == tlist[1].coords("longitude")[0].points
        ).all()
        assert (
            tlist[0].coords("latitude")[0].points
            == tlist[1].coords("latitude")[0].points
        ).all()

    error_msg = re.escape(
        "Cannot unify latitude and longitude, relative difference in co-ordinates "
        "is greater than {}".format(ttol)
    )
    with pytest.raises(ValueError, match=error_msg):
        tlist = get_starting_list(ttol * 1.01)
        if default:
            unify_lat_lon(tlist)
        else:
            unify_lat_lon(tlist, rtol=ttol)


@pytest.mark.parametrize("lazy", [True, False])
@pytest.mark.parametrize("transpose", [True, False])
@patch.object(iris.cube.Cube, "has_lazy_data")
def test_broadcast_onto_lat_lon_grid(
    mock_has_lazy_data, test_generic_tas_cube, test_sftlf_file, lazy, transpose
):
    original = iris.load_cube(test_sftlf_file).data
    if transpose:
        ar_to_broadcast = np.transpose(original)
    else:
        ar_to_broadcast = original

    mock_has_lazy_data.return_value = lazy

    res = broadcast_onto_lat_lon_grid(test_generic_tas_cube, ar_to_broadcast)

    assert isinstance(res, da.Array) if lazy else isinstance(res, np.ndarray)
    expected = np.broadcast_to(original, test_generic_tas_cube.cube.shape)

    np.testing.assert_allclose(res, expected)


def test_broadcast_onto_lat_lon_grid_errors(test_generic_tas_cube, test_sftlf_file):
    ar_to_broadcast = iris.load_cube(test_sftlf_file).data[1:, 1:]
    error_msg = re.escape(
        "the ``array_in`` must be the same shape as the "
        "cube's longitude-latitude grid"
    )
    with pytest.raises(AssertionError, match=error_msg):
        broadcast_onto_lat_lon_grid(test_generic_tas_cube, ar_to_broadcast)
