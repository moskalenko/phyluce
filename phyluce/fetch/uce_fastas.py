#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
(c) 2013 Brant Faircloth || http://faircloth-lab.org/
All rights reserved.

This code is distributed under a 3-clause BSD license. Please see
LICENSE.txt for more information.

Created on 27 December 2013 15:12 PST (-0800)
"""

from __future__ import absolute_import
import os
import re
import sqlite3
import ConfigParser
from collections import defaultdict

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

from phyluce.log import setup_logging
from phyluce.common import get_names_from_config


def get_nodes_for_uces(c, organism, uces, extend=False, notstrict=False):
    # get only those UCEs we know are in the set
    uces = [("\'{0}\'").format(u) for u in uces]
    if not extend:
        query = ("SELECT lower({0}), uce FROM match_map "
                 "where uce in ({1})".format(organism, ','.join(uces)))
    else:
        query = ("SELECT lower({0}), uce FROM extended.match_map "
                 "where uce in ({1})".format(organism, ','.join(uces)))
    c.execute(query)
    rows = c.fetchall()
    node_dict = defaultdict()
    missing = []
    for node in rows:
        if node[0] is not None:
            match = re.search(
                '^(node_\d+|comp\d+_c\d+_seq\d+)\(([+-])\)',
                node[0]
            )
            node_dict[match.groups()[0]] = (node[1], match.groups()[1])
        elif notstrict:
            missing.append(node[1])
        else:
            raise IOError("Complete matrices should have no missing data")
    return node_dict, missing


def find_file(contigs, name):
    extensions = [
        '.fa',
        '.fasta',
        '.contigs.fasta',
        '.contigs.fa',
        '.gz',
        '.fasta.gz',
        '.fa.gz'
    ]
    for ext in extensions:
        reads1 = os.path.join(contigs, name) + ext
        reads2 = os.path.join(contigs, name.replace('-', '_')) + ext
        for reads in [reads1, reads2]:
            if os.path.isfile(reads):
                break
            elif os.path.isfile(reads.lower()):
                reads = reads.lower()
                break
            else:
                reads = None
        if reads is not None:
            break
    if reads is None:
        raise ValueError("Cannot find the a fasta file for {} with any "
                         "of the extensions ({}) ".format(name,
                                                          ', '.join(extensions)
                                                          ))
    return reads


def get_contig_name(header):
    """
    parse the contig name from the header of either velvet/trinity
    assembled contigs
    """
    match = re.search("^(Node_\d+|NODE_\d+|comp\d+_c\d+_seq\d+).*", header)
    return match.groups()[0]


def replace_and_remove_bases(regex, seq, count):
    new_seq_string = str(seq.seq)
    if regex.search(new_seq_string):
        new_seq_string = re.sub(regex, "", new_seq_string)
        #print "\tReplaced < 20 ambiguous bases in {0}".format(seq.id)
        count += 1
    new_seq_string = re.sub("^[acgtn]+", "", new_seq_string)
    new_seq_string = re.sub("[acgtn]+$", "", new_seq_string)
    new_seq = Seq(new_seq_string)
    new_seq_record = SeqRecord(new_seq, id=seq.id, name='', description='')
    return new_seq_record, count


def main(args, parser):
    # setup logging
    log, my_name = setup_logging(args)
    # parse the config file - allowing no values (e.g. no ":" in config file)
    config = ConfigParser.RawConfigParser(allow_no_value=True)
    config.optionxform = str
    config.read(args.match_count_output)
    # connect to the database
    conn = sqlite3.connect(args.locus_db)
    c = conn.cursor()
    # attach to external database, if passed as option
    if args.extend_locus_db:
        log.info("Attaching extended database {}".format(
            os.path.basename(args.extend_locus_db))
        )
        query = "ATTACH DATABASE '{0}' AS extended".format(
            args.extend_locus_db
        )
        c.execute(query)
    organisms = get_names_from_config(config, 'Organisms')
    log.info("There are {} taxa in the match-count-config file named {}".format(
        len(organisms),
        os.path.basename(args.match_count_output)
    ))
    uces = get_names_from_config(config, 'Loci')
    if not args.incomplete_matrix:
        log.info("There are {} shared UCE loci in a COMPLETE matrix".format(
            len(uces))
        )
    else:
        log.info("There are {} UCE loci in an INCOMPLETE matrix".format(
            len(uces))
        )
    regex = re.compile("[N,n]{1,21}")
    if args.incomplete_matrix:
        incomplete_outf = open(args.incomplete_matrix, 'w')
    with open(args.output, 'w') as uce_fasta_out:
        for organism in organisms:
            text = "Getting UCE loci for {0}".format(organism)
            log.info(text.center(65, "-"))
            written = []
            # going to need to do something more generic w/ suffixes
            name = organism.replace('_', '-')
            if args.incomplete_matrix:
                if not organism.endswith('*'):
                    reads = find_file(args.contigs, name)
                    node_dict, missing = get_nodes_for_uces(
                        c,
                        organism,
                        uces,
                        extend=False,
                        notstrict=True
                    )
                elif args.extend_locus_contigs:
                    # remove the asterisk
                    name = name.rstrip('*')
                    reads = find_file(args.extend_locus_contigs, name)
                    node_dict, missing = get_nodes_for_uces(
                        c,
                        organism.rstrip('*'),
                        uces,
                        extend=True,
                        notstrict=True
                    )
            else:
                if not name.endswith('*'):
                    reads = find_file(args.contigs, name)
                    node_dict, missing = get_nodes_for_uces(c, organism, uces)
                elif name.endswith('*') and args.extend_locus_contigs:
                    # remove the asterisk
                    name = name.rstrip('*')
                    reads = find_file(args.extend_locus_contigs, name)
                    node_dict, missing = get_nodes_for_uces(
                        c,
                        organism.rstrip('*'),
                        uces,
                        extend=True
                    )
            count = 0
            log.info("There are {} UCE loci for {}".format(
                len(node_dict),
                organism
                ))
            log.info("Parsing and renaming contigs for {}".format(organism))
            for seq in SeqIO.parse(open(reads, 'rU'), 'fasta'):
                name = get_contig_name(seq.id).lower()
                if name in node_dict.keys():
                    seq.id = "{0}_{1} |{0}".format(
                        node_dict[name][0],
                        organism.rstrip('*')
                    )
                    seq.name = ''
                    seq.description = ''
                    # deal with strandedness because aligners sometimes
                    # dont, which is annoying
                    if node_dict[name][1] == '-':
                        seq.seq = seq.seq.reverse_complement()
                    # Replace any occurrences of <21 Ns in a given sequence
                    # with blanks.  These should gap out during alignment.
                    # Also, replace leading/trailing lowercase bases from
                    # velvet assemblies. Lowercase bases indicate low coverage,
                    # and these have been problematic in downstream alignments)
                    seq, count = replace_and_remove_bases(regex, seq, count)
                    uce_fasta_out.write(seq.format('fasta'))
                    written.append(str(node_dict[name][0]))
                else:
                    pass
            if count > 0:
                log.info(
                    "Replaced <20 ambiguous bases (N) in {} "
                    "contigs for {}".format(count, organism))
            if args.incomplete_matrix and missing:
                log.info("Writing missing locus information to {}".format(
                    args.incomplete_matrix)
                )
                incomplete_outf.write("[{0}]\n".format(organism))
                for name in missing:
                    incomplete_outf.write("{0}\n".format(name))
                    written.append(name)
            assert set(written) == set(uces), "UCE names do not match"
    text = " Completed {} ".format(my_name)
    log.info(text.center(65, "="))
