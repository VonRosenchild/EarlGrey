import argparse
import shutil
import re
import os
import subprocess
from Bio import SeqIO
import pandas as pd
import numpy as np
from pybedtools import BedTool
from pyfaidx import Fasta
import logging
import time
import datetime
pd.options.mode.chained_assignment = None  # default='warn'

LOGGER = logging.getLogger(__name__)

## Set up input arguments
def get_args():
	parser = argparse.ArgumentParser(description="Will process a blast output generated using a file of putative TEs (usually generated by RepeatModeler. For each putative consensus in the input putative TE library, it will generate an aligned file with N buffered instances from the queried genome, the input consensus, and, if requested, a new revised and extended consensus for inspection.", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
	parser.add_argument('-g', '--genome_fasta', type=str, help='Name of the fasta formatted genome to be queried.', required=True)
	parser.add_argument('-b', '--blastfile', type=str, help='Blast output to be used. Must be formatted using "outfmt 6".', required = True)
	parser.add_argument('-l', '--library', type=str, help='Library of putative TE consensus sequences to be extracted and aligned. Must be in fasta format with no # or / in the headers.', required = True)
	parser.add_argument('-lb', '--leftbuffer', type=int, help='Left buffer size. The number of bp of flanking sequence for each hit to be extracted along with the hit. Optional, Default = 1000', default = 1000)
	parser.add_argument('-rb', '--rightbuffer', type=int, help='Right beffer size. The number of bp of flanking sequence for each hit to be extracted along with the hit. Optional, Default = 1000', default = 1000)
	parser.add_argument('-n', '--hitnumber', type=int, help='The number of hits to be exracted. Optional. Default = 50.', default = 50)
	parser.add_argument('-a', '--align', type=str, help='Align the output fasta file, y or n?. Default is y.', default = 'y')
	parser.add_argument('-t', '--trimal', type=str, help='Use trimal to remove low-aligning regions, y or n? Trimal can sometimes encounter an error that prevents it from working, this results in an empty file in downstream analyses. Default is y.', default = 'y')
	parser.add_argument('-e', '--emboss', type=str, help='Generate a trimal/emboss consensus, y or n. Optional.', default = 'y')
	parser.add_argument("-log", "--log_level", default="INFO")

	args = parser.parse_args()
	GENOMEFA = args.genome_fasta
	BLAST = args.blastfile
	LIB = args.library
	LBUFFER = args.leftbuffer
	RBUFFER = args.rightbuffer
	HITNUM = args.hitnumber
	ALIGN = args.align
	TRIMAL = args.trimal
	EMBOSS = args.emboss
	LOG = args.log_level

	return GENOMEFA, BLAST, LIB, LBUFFER, RBUFFER, HITNUM, ALIGN, TRIMAL, EMBOSS, LOG

## Create TE outfiles function. Creates files for populating with blast hits.
def CREATE_TE_OUTFILES(LIBRARY):
	for record in SeqIO.parse(LIBRARY, 'fasta'):
		NEWID = re.sub('#', '__', record.id)
		NEWID = re.sub('/', '___', NEWID)
		record.id = 'CONSENSUS-' + NEWID
		record.description = ''
		SeqIO.write(record, 'tmpTEfiles/' + NEWID + '.fa', 'fasta')
				
## Organize blast hits function. Will read in blast file, sort based on e-value and bitscore, deterine top BUFFER hits for extraction, extract, and combine with TE file from previous function.
def EXTRACT_BLAST_HITS(GENOME, BLAST, LBUFFER, RBUFFER, HITNUM):
##Read in blast data
	BLASTDF = pd.read_table(BLAST, sep='\t', names=['QUERYNAME', 'SCAFFOLD', 'C', 'D', 'E', 'F', 'QUERYSTART', 'QUERYSTOP', 'SCAFSTART', 'SCAFSTOP', 'E-VALUE', 'BITSCORE'])
##Convert to bed format
	BLASTBED = BLASTDF[['SCAFFOLD', 'SCAFSTART', 'SCAFSTOP', 'QUERYNAME', 'E-VALUE', 'BITSCORE']]
	BLASTBED.insert(5, 'STRAND', '+')
	BLASTBED.loc[BLASTBED.SCAFSTOP < BLASTBED.SCAFSTART, 'STRAND'] = '-'
	BLASTBED.SCAFSTART, BLASTBED.SCAFSTOP = np.where(BLASTBED.SCAFSTART > BLASTBED.SCAFSTOP, [BLASTBED.SCAFSTOP, BLASTBED.SCAFSTART], [BLASTBED.SCAFSTART, BLASTBED.SCAFSTOP])
##Generate list of query names
	QUERYLIST = BLASTBED.QUERYNAME.unique()
	LOGGER.info('There are ' + str(len(QUERYLIST)) + ' consensus sequences to process')
#	COUNTER = 1
##Sort subsets of df based on query names, keep the top BUFFER hits, make bedfiles, extract, and combine
	for QUERY in QUERYLIST:
#		LOGGER.info('Extracting for TE: ' + str(COUNTER))
		QUERYFRAME = BLASTBED[BLASTBED['QUERYNAME'] == QUERY]
		QUERYFRAME = QUERYFRAME.sort_values(by=['E-VALUE', 'BITSCORE'], ascending=[True, False])
		QUERYFRAME = QUERYFRAME.head(HITNUM)
		QUERYFRAMESAVE = 'tmpbedfiles/' + QUERY + '.bed'
		QUERYFRAME.to_csv('tmpbedfiles/' + QUERY + '.bed', sep='\t', header=False, index=False)
		CURRENTBED = BedTool('tmpbedfiles/' + QUERY + '.bed')
		GENOMEPREFIX = os.path.splitext(GENOME)[0]
		SLOPBED = CURRENTBED.slop(g=GENOMEPREFIX + '.fai', l=LBUFFER, r=RBUFFER, output='tmpbedfiles/' + QUERY + '.slop')
		SLOPBED = BedTool('tmpbedfiles/' + QUERY + '.slop')
		FASTA = SLOPBED.sequence(fi=GENOME, s=True)
		FASTASAVE = SLOPBED.save_seqs('tmpextracts/' + QUERY + '.fa')
		os.remove('tmpbedfiles/' +  QUERY + '.slop')
		os.remove('tmpbedfiles/' + QUERY + '.bed')
		subprocess.run('cat {} {} >{}'.format('tmpextracts/' + QUERY + '.fa', 'tmpTEfiles/' + QUERY +'.fa', 'catTEfiles/' + QUERY +'.fa'), shell=True)
#		COUNTER = COUNTER + 1
		
##Alignment function
def MUSCLE(TOALIGN):
	TOALIGNPREFIX = os.path.splitext(TOALIGN)[0]
	SOFTWARE = '/usr/bin'
	subprocess.check_call(SOFTWARE + '/muscle -in {} -out {}'.format('catTEfiles/' + TOALIGN, 'muscle/' + TOALIGNPREFIX + '.fa'), shell=True)

##Consensus generation function
def CONSENSUSGEN(ALIGNED):
	FILEPREFIX = os.path.splitext(ALIGNED)[0] 
	SOFTWARE = '/home/toby/Programs/'
	if TRIMAL == 'y':
		subprocess.run(SOFTWARE + 'trimal/source/trimal -in {} -gt 0.6 -cons 60 -fasta -out {}'.format('muscle/' + ALIGNED, 'muscle/' + FILEPREFIX + '_trimal.fa'), shell=True)
		subprocess.run(SOFTWARE + 'EMBOSS-6.6.0/emboss/cons -sequence muscle/' + FILEPREFIX + '_trimal.fa -outseq muscle/' + FILEPREFIX + '_cons.fa -name ' + FILEPREFIX + '_cons -plurality 3 -identity 3', shell=True)
		subprocess.run('cat {} {} >{}'.format('muscle/' + FILEPREFIX + '_trimal.fa', 'muscle/' + FILEPREFIX + '_cons.fa', 'consensusfiles/' + FILEPREFIX + '_cons.fa'), shell=True)
	if TRIMAL == 'n':
#		subprocess.run(SOFTWARE + 'trimal/source/trimal -in {} -gt 0.6 -cons 60 -fasta -out {}'.format('muscle/' + ALIGNED, 'muscle/' + FILEPREFIX + '_trimal.fa'), shell=True)
		subprocess.run(SOFTWARE + 'EMBOSS-6.6.0/emboss/cons -sequence muscle/' + ALIGNED + ' -outseq muscle/' + FILEPREFIX + '_cons.fa -name ' + FILEPREFIX + '_cons -plurality 3 -identity 3', shell=True)
		subprocess.run('cat {} {} >{}'.format('muscle/' + ALIGNED, 'muscle/' + FILEPREFIX + '_cons.fa', 'consensusfiles/' + FILEPREFIX + '_cons.fa'), shell=True)

def DIRS(DIR):
	if os.path.exists(DIR):
		shutil.rmtree(DIR)
	os.mkdir(DIR)

####MAIN function
def main():	
##Get input arguments
	GENOMEFA, BLAST, LIB, LBUFFER, RBUFFER, HITNUM, ALIGN, TRIMAL, EMBOSS, LOG = get_args()

# Setup logging and script timing
	handlers = [logging.FileHandler('extract_align.log'), logging.StreamHandler()]
	logging.basicConfig(format='', handlers = handlers)
	logging.getLogger().setLevel(getattr(logging, LOG.upper()))

	start_time = time.time()

	LOGGER.info('#\n# extract_align.py\n#')

	LOGGER.info('Genome file: ' + GENOMEFA)
	LOGGER.info('Blast file: ' + BLAST)
	LOGGER.info('TE library: ' + LIB)
	LOGGER.info('Left buffer size: ' + str(LBUFFER))
	LOGGER.info('Right buffer size: ' + str(RBUFFER))
	LOGGER.info('Number of hits evaluated: ' + str(HITNUM))
	LOGGER.info('Muscle alignment = ' + ALIGN)
	LOGGER.info('Trimal processing = ' + TRIMAL)
	LOGGER.info('Emboss consensus = ' + EMBOSS)
	LOGGER.info('Log level: ' + LOG)

## Index the genome 
	LOGGER.info('Indexing the genome')
	GENOMEIDX = Fasta(GENOMEFA)
	GENOMEPREFIX = os.path.splitext(GENOMEFA)[0]
	FAIDX = pd.read_table(GENOMEFA + '.fai', sep='\t', names=['one', 'two', 'three', 'four', 'five'])
	FAIDX = FAIDX[['one', 'two']]
	FAIDX.to_csv(GENOMEPREFIX + '.fai', sep='\t', header=False, index=False)
		
## Set up directories	
	LOGGER.info('Creating tmp and permanent directories')
	DIRS('tmpTEfiles')
	DIRS('tmpbedfiles')
	if ALIGN == 'y':
		DIRS('muscle')
	if EMBOSS == 'y':
		DIRS('consensusfiles')
	DIRS('tmpextracts')
	DIRS('catTEfiles')
	
##Determine optional arguments and print to screen.
	if ALIGN == 'n' and EMBOSS == 'y':
		LOGGER.info('Input is contradictory. Generating a new consensus with emboss requires muscle alignment.')
	elif ALIGN == 'y' and EMBOSS == 'y':
		LOGGER.info('Output files will be aligned and a new consensus will be generated with emboss and trimal.')
	elif ALIGN == 'y' and EMBOSS == 'n':
		LOGGER.info('Output files will be aligned but without a new emboss/trimal consensus.')
	elif ALIGN == 'n' and EMBOSS == 'n':
		LOGGER.info('Extractions will be made but no alignment.')
	else:
		LOGGER.info('Invalid input for either align, or emboss, or both.')

##Create TE out files to populate with blast hits
	CREATE_TE_OUTFILES(LIB)
	
##Extract hits and combine them with the TE out files if flagged
	EXTRACT_BLAST_HITS(GENOMEFA, BLAST, LBUFFER, RBUFFER, HITNUM)
	
##Align extracted hits if flagged
	if ALIGN == 'y':
		COUNTER = 1
		for FILE in os.listdir('tmpextracts'):
			LOGGER.info('Aligning TE: ' + str(COUNTER))
			MUSCLE(FILE)
			COUNTER = COUNTER + 1

##Generate new consensus with emboss if flagged
	if EMBOSS == 'y':
		for FILE in os.listdir('muscle'):
			CONSENSUSGEN(FILE)
			
##Remove empty tmp directories and unneeded files
	LOGGER.info('Removing tmp directories and extraneous files')
	shutil.rmtree('tmpbedfiles/')
	shutil.rmtree('tmpextracts/')
	shutil.rmtree('tmpTEfiles/')
	#FILES = [F for F in os.listdir('muscle/') if F.endswith('_cons.fa')]
	#for FILE in FILES:
	#	os.remove('muscle/' + FILE)
	#FILES = [F for F in os.listdir('muscle/') if F.endswith('_trimal.fa')]
	#for FILE in FILES:
	#	os.remove('muscle/' + FILE)
	
	end_time = time.time()
	LOGGER.info('Run time: ' + str(datetime.timedelta(seconds=end_time-start_time)))
#
# Wrap script functionality in main() to avoid automatic execution
# when imported ( e.g. when help is called on file )
#
if __name__ =="__main__":main()
		
