"""
test_time_overlap_validation.py — Tests for time overlap validation

Tests the validate_time_overlap() function which ensures data sources
have overlapping time ranges before analysis.
"""

import pytest
import pandas as pd
from run_analysis import validate_time_overlap


class TestTimeOverlapValidation:
    """Tests for validate_time_overlap function."""
    
    def test_overlapping_ranges_passes(self):
        """Two sources with overlapping ranges should pass validation."""
        ha = pd.DataFrame(
            {"temp": [20.0, 21.0, 22.0]},
            index=pd.date_range("2024-01-01 00:00", periods=3, freq="1h", tz="UTC")
        )
        om = pd.DataFrame(
            {"rain": [0.0, 0.1, 0.0]},
            index=pd.date_range("2024-01-01 01:00", periods=3, freq="1h", tz="UTC")
        )
        
        # Should not raise
        validate_time_overlap(ha, om, None, None)
    
    def test_complete_overlap_passes(self):
        """One source completely within another should pass."""
        ha = pd.DataFrame(
            {"temp": [20.0] * 10},
            index=pd.date_range("2024-01-01 00:00", periods=10, freq="1h", tz="UTC")
        )
        om = pd.DataFrame(
            {"rain": [0.0] * 5},
            index=pd.date_range("2024-01-01 02:00", periods=5, freq="1h", tz="UTC")
        )
        
        # Should not raise
        validate_time_overlap(ha, om, None, None)
    
    def test_identical_ranges_passes(self):
        """Identical time ranges should pass."""
        times = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
        ha = pd.DataFrame({"temp": [20.0] * 5}, index=times)
        om = pd.DataFrame({"rain": [0.0] * 5}, index=times)
        
        # Should not raise
        validate_time_overlap(ha, om, None, None)
    
    def test_disjoint_ranges_raises(self):
        """Non-overlapping ranges should raise ValueError."""
        ha = pd.DataFrame(
            {"temp": [20.0, 21.0, 22.0]},
            index=pd.date_range("2024-01-01 00:00", periods=3, freq="1h", tz="UTC")
        )
        om = pd.DataFrame(
            {"rain": [0.0, 0.1, 0.0]},
            index=pd.date_range("2024-01-02 00:00", periods=3, freq="1h", tz="UTC")
        )
        
        with pytest.raises(ValueError, match="No time overlap"):
            validate_time_overlap(ha, om, None, None)
    
    def test_adjacent_ranges_raises(self):
        """Adjacent but non-overlapping ranges should raise."""
        ha = pd.DataFrame(
            {"temp": [20.0, 21.0]},
            index=pd.date_range("2024-01-01 00:00", periods=2, freq="1h", tz="UTC")
        )
        # Starts exactly where ha ends
        om = pd.DataFrame(
            {"rain": [0.0, 0.1]},
            index=pd.date_range("2024-01-01 02:00", periods=2, freq="1h", tz="UTC")
        )
        
        with pytest.raises(ValueError, match="No time overlap"):
            validate_time_overlap(ha, om, None, None)
    
    def test_single_source_raises(self):
        """Single data source should raise (need at least 2)."""
        ha = pd.DataFrame(
            {"temp": [20.0, 21.0]},
            index=pd.date_range("2024-01-01", periods=2, freq="1h", tz="UTC")
        )
        
        with pytest.raises(ValueError, match="Need at least 2 data sources"):
            validate_time_overlap(ha, None, None, None)
    
    def test_empty_dataframes_treated_as_none(self):
        """Empty DataFrames should be treated as missing sources."""
        ha = pd.DataFrame(
            {"temp": [20.0, 21.0]},
            index=pd.date_range("2024-01-01", periods=2, freq="1h", tz="UTC")
        )
        om_empty = pd.DataFrame()
        
        with pytest.raises(ValueError, match="Need at least 2 data sources"):
            validate_time_overlap(ha, om_empty, None, None)
    
    def test_three_sources_all_overlap(self):
        """Three sources with common overlap should pass."""
        ha = pd.DataFrame(
            {"temp": [20.0] * 10},
            index=pd.date_range("2024-01-01 00:00", periods=10, freq="1h", tz="UTC")
        )
        om = pd.DataFrame(
            {"rain": [0.0] * 8},
            index=pd.date_range("2024-01-01 02:00", periods=8, freq="1h", tz="UTC")
        )
        yx = pd.DataFrame(
            {"yx_rain_prob": [30.0] * 6},
            index=pd.date_range("2024-01-01 03:00", periods=6, freq="1h", tz="UTC")
        )
        
        # All three overlap in 03:00-09:00 range
        validate_time_overlap(ha, om, yx, None)
    
    def test_three_sources_no_common_overlap_raises(self):
        """Three sources with no common overlap should raise."""
        ha = pd.DataFrame(
            {"temp": [20.0] * 5},
            index=pd.date_range("2024-01-01 00:00", periods=5, freq="1h", tz="UTC")
        )
        om = pd.DataFrame(
            {"rain": [0.0] * 5},
            index=pd.date_range("2024-01-01 03:00", periods=5, freq="1h", tz="UTC")
        )
        # Yandex after both ha and om
        yx = pd.DataFrame(
            {"yx_rain_prob": [30.0] * 5},
            index=pd.date_range("2024-01-01 10:00", periods=5, freq="1h", tz="UTC")
        )
        
        # HA overlaps with OM, but yx is disjoint from both
        with pytest.raises(ValueError, match="No time overlap"):
            validate_time_overlap(ha, om, yx, None)
    
    def test_minimal_overlap_passes(self):
        """Minimal overlap (more than one timestamp) should pass validation."""
        ha = pd.DataFrame(
            {"temp": [20.0, 21.0, 22.0]},
            index=pd.DatetimeIndex([
                "2024-01-01 00:00:00",
                "2024-01-01 01:00:00",
                "2024-01-01 02:00:00"
            ], tz="UTC")
        )
        om = pd.DataFrame(
            {"rain": [0.0, 0.1, 0.2]},
            index=pd.DatetimeIndex([
                "2024-01-01 01:00:00",
                "2024-01-01 02:00:00",
                "2024-01-01 03:00:00"
            ], tz="UTC")
        )
        
        # Overlap is 01:00:00 to 02:00:00 (1 hour)
        validate_time_overlap(ha, om, None, None)
    
    def test_error_message_shows_all_ranges(self):
        """Error message should show time ranges of all sources."""
        ha = pd.DataFrame(
            {"temp": [20.0]},
            index=pd.DatetimeIndex(["2024-01-01 00:00:00"], tz="UTC")
        )
        om = pd.DataFrame(
            {"rain": [0.0]},
            index=pd.DatetimeIndex(["2024-01-02 00:00:00"], tz="UTC")
        )
        
        with pytest.raises(ValueError) as exc_info:
            validate_time_overlap(ha, om, None, None)
        
        error_msg = str(exc_info.value)
        assert "HA" in error_msg
        assert "Open-Meteo" in error_msg
        assert "2024-01-01" in error_msg
        assert "2024-01-02" in error_msg
    
    def test_small_overlap_warns(self, capsys):
        """Less than 24 hours overlap should emit warning."""
        ha = pd.DataFrame(
            {"temp": [20.0, 21.0]},
            index=pd.date_range("2024-01-01 00:00", periods=2, freq="1h", tz="UTC")
        )
        om = pd.DataFrame(
            {"rain": [0.0, 0.1]},
            index=pd.date_range("2024-01-01 00:30", periods=2, freq="1h", tz="UTC")
        )
        
        validate_time_overlap(ha, om, None, None)
        
        captured = capsys.readouterr()
        assert "WARN" in captured.err
        assert "hours of data overlap" in captured.err
    
    def test_large_overlap_no_warning(self, capsys):
        """More than 24 hours overlap should not warn."""
        ha = pd.DataFrame(
            {"temp": [20.0] * 50},
            index=pd.date_range("2024-01-01", periods=50, freq="1h", tz="UTC")
        )
        om = pd.DataFrame(
            {"rain": [0.0] * 50},
            index=pd.date_range("2024-01-01 01:00", periods=50, freq="1h", tz="UTC")
        )
        
        validate_time_overlap(ha, om, None, None)
        
        captured = capsys.readouterr()
        assert "WARN" not in captured.err
    
    def test_meteostat_fourth_source(self):
        """Meteostat as fourth source should be validated."""
        ha = pd.DataFrame(
            {"temp": [20.0] * 10},
            index=pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC")
        )
        om = pd.DataFrame(
            {"rain": [0.0] * 10},
            index=pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC")
        )
        ms = pd.DataFrame(
            {"ms_pres": [1013.0] * 10},
            index=pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC")
        )
        
        # Should pass with all three overlapping
        validate_time_overlap(ha, om, None, ms)
    
    def test_meteostat_disjoint_raises(self):
        """Disjoint Meteostat should raise."""
        ha = pd.DataFrame(
            {"temp": [20.0] * 5},
            index=pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
        )
        om = pd.DataFrame(
            {"rain": [0.0] * 5},
            index=pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
        )
        ms = pd.DataFrame(
            {"ms_pres": [1013.0] * 5},
            index=pd.date_range("2024-01-10", periods=5, freq="1h", tz="UTC")
        )
        
        with pytest.raises(ValueError, match="No time overlap"):
            validate_time_overlap(ha, om, None, ms)


class TestTimeOverlapEdgeCases:
    """Edge cases for time overlap validation."""
    
    def test_single_timestamp_per_source(self):
        """Sources with single timestamp each should fail (no real overlap)."""
        ha = pd.DataFrame(
            {"temp": [20.0]},
            index=pd.DatetimeIndex(["2024-01-01 12:00:00"], tz="UTC")
        )
        om = pd.DataFrame(
            {"rain": [0.0]},
            index=pd.DatetimeIndex(["2024-01-01 12:00:00"], tz="UTC")
        )
        
        # Single matching timestamp: overlap_start == overlap_end, should fail
        with pytest.raises(ValueError, match="No time overlap"):
            validate_time_overlap(ha, om, None, None)
    
    def test_single_timestamp_offset(self):
        """Single timestamp each, offset by 1 second."""
        ha = pd.DataFrame(
            {"temp": [20.0]},
            index=pd.DatetimeIndex(["2024-01-01 12:00:00"], tz="UTC")
        )
        om = pd.DataFrame(
            {"rain": [0.0]},
            index=pd.DatetimeIndex(["2024-01-01 12:00:01"], tz="UTC")
        )
        
        # No overlap: ha max < om min
        with pytest.raises(ValueError, match="No time overlap"):
            validate_time_overlap(ha, om, None, None)
    
    def test_reverse_chronological_order(self):
        """Sources should work regardless of internal order."""
        ha = pd.DataFrame(
            {"temp": [20.0, 21.0, 22.0]},
            index=pd.DatetimeIndex([
                "2024-01-01 02:00:00",
                "2024-01-01 01:00:00",
                "2024-01-01 00:00:00",
            ], tz="UTC")
        )
        om = pd.DataFrame(
            {"rain": [0.0, 0.1, 0.2]},
            index=pd.DatetimeIndex([
                "2024-01-01 03:00:00",
                "2024-01-01 02:00:00",
                "2024-01-01 01:00:00",
            ], tz="UTC")
        )
        
        # Should find overlap despite reverse ordering
        validate_time_overlap(ha, om, None, None)
