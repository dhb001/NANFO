# SNMP protocol-response fixtures

These are checked-in, hand-authored recordings of the numeric-OID typed output
contract (`snmpget -One`), not captures from physical hardware. The adapter tests
replay these bytes through the real response parser. They establish parser/rate/
failure semantics only, not physical acceptance or proof of vendor compatibility.

At 1 Gbit/s over ten seconds, RX grows by 625,000,000 octets and TX by 250,000,000:
500 Mbit/s RX, 200 Mbit/s TX and 50% busiest-direction utilization. Negative
cases mutate the response transcript explicitly; no real device is contacted.
