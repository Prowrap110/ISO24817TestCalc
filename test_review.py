import unittest
from calculator import calculate
class ReviewTests(unittest.TestCase):
    def test_impossible_defect_width(self):
        with self.assertRaises(ValueError): calculate({'defect_width':2000})
    def test_overflow_input(self):
        with self.assertRaises(ValueError): calculate({'yield_strength':1e308})
if __name__=='__main__': unittest.main()
