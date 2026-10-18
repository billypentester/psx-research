import unittest
from unittest.mock import patch

from pipeline.run_company import main


class TestRunCompany(unittest.TestCase):
    @patch("pipeline.run_company.run", return_value=0)
    @patch(
        "pipeline.run_company.argparse.ArgumentParser.parse_args",
        return_value=type(
            "Args",
            (),
            {
                "company": "ABC",
                "fetch_discover": False,
                "url": [],
                "delay": 2.0,
                "validate": True,
                "allow_empty": False,
            },
        )(),
    )
    def test_runs_initialization_then_analysis(self, _args, run):
        self.assertEqual(main(), 0)
        self.assertEqual(run.call_count, 2)
        self.assertIn("init_company.py", run.call_args_list[0].args[0][1])
        self.assertIn("run_analysis.py", run.call_args_list[1].args[0][1])


if __name__ == "__main__":
    unittest.main()
